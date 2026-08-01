"""Tests for the sha256-addressed PCM streaming path.

Covers the protocol's digest handling and the resolver's database lookup --
the parts that replaced the old "client sends a file name" scheme. Decoding
itself is ffmpeg's job and is not re-tested here.
"""

import hashlib
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from .models import Track
from .streaming import protocol, resolver


class TempMediaMixin:
    """Save uploads under a throwaway MEDIA_ROOT.

    Without this the suite writes into the real media/ folder and leaves the
    files behind, since destroying the test database says nothing about files.
    """

    @classmethod
    def setUpClass(cls):
        cls._media_root = tempfile.mkdtemp(prefix='btr-test-media-')
        cls._media_override = override_settings(MEDIA_ROOT=cls._media_root)
        cls._media_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._media_override.disable()
        shutil.rmtree(cls._media_root, ignore_errors=True)


class DigestValidationTests(TestCase):
    def test_accepts_a_lowercase_digest(self):
        self.assertTrue(protocol.is_sha256_hex('a' * 64))

    def test_accepts_an_uppercase_digest(self):
        self.assertTrue(protocol.is_sha256_hex('A' * 64))

    def test_rejects_wrong_length(self):
        self.assertFalse(protocol.is_sha256_hex('a' * 63))
        self.assertFalse(protocol.is_sha256_hex('a' * 65))

    def test_rejects_non_hex_characters(self):
        self.assertFalse(protocol.is_sha256_hex('g' * 64))

    def test_rejects_empty_and_none(self):
        self.assertFalse(protocol.is_sha256_hex(''))
        self.assertFalse(protocol.is_sha256_hex(None))

    def test_rejects_path_traversal(self):
        # The protocol cannot express a path at all: these are simply not
        # digests, so they never reach the database.
        for attempt in ('../../etc/passwd', 'club_music.ogg', '/etc/passwd',
                        'http://example.com/a.mp3'):
            self.assertFalse(protocol.is_sha256_hex(attempt), attempt)

    def test_normalizes_case(self):
        self.assertEqual(protocol.normalize_digest('AbCd'), 'abcd')

    def test_request_bound_is_one_digest(self):
        self.assertEqual(protocol.MAX_REQUEST_LEN, 64)


class FindTrackTests(TempMediaMixin, TestCase):
    def setUp(self):
        payload = b'not real audio, only the row matters here'
        self.digest = hashlib.sha256(payload).hexdigest()
        self.track = Track.objects.create(
            file=SimpleUploadedFile('song.mp3', payload, content_type='audio/mpeg'),
            original_filename='song.mp3',
            title='Test Song',
            file_size=len(payload),
            mime_type='audio/mpeg',
            sha256=self.digest,
        )

    def test_finds_a_track_by_digest(self):
        self.assertEqual(resolver.find_track(self.digest), self.track)

    def test_finds_a_track_given_an_uppercase_digest(self):
        self.assertEqual(resolver.find_track(self.digest.upper()), self.track)

    def test_unknown_digest_returns_none(self):
        self.assertIsNone(resolver.find_track('0' * 64))

    def test_malformed_digest_returns_none(self):
        self.assertIsNone(resolver.find_track('not-a-digest'))

    def test_malformed_digest_never_queries(self):
        # A bad digest is rejected outright rather than becoming a query.
        with self.assertNumQueries(0):
            resolver.find_track('../../etc/passwd')

    def test_undecodable_file_yields_no_source(self):
        # The row exists, but the bytes are not audio -- the server turns this
        # into STATUS_SERVER_ERROR rather than pretending the track is missing.
        self.assertIsNone(resolver.open_source(self.track))


class TrackApiTests(TempMediaMixin, TestCase):
    """The client can only request a stream if the API hands it the digest."""

    def setUp(self):
        payload = b'another fake track'
        self.digest = hashlib.sha256(payload).hexdigest()
        Track.objects.create(
            file=SimpleUploadedFile('b.mp3', payload, content_type='audio/mpeg'),
            original_filename='b.mp3',
            title='Findable',
            artist='Tester',
            file_size=len(payload),
            mime_type='audio/mpeg',
            sha256=self.digest,
        )

    def test_track_list_exposes_the_digest(self):
        response = self.client.get('/api/tracks/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['tracks'][0]['sha256'], self.digest)

    def test_search_exposes_the_digest(self):
        response = self.client.get('/api/search/', {'q': 'Findable'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['results'][0]['sha256'], self.digest)

    def test_dashboard_renders_the_digest_for_the_player(self):
        response = self.client.get('/')
        self.assertContains(response, f'data-sha256="{self.digest}"')


class FolderUploadTests(TempMediaMixin, TestCase):
    """POST /api/tracks/upload-folder/ -- many files in one request."""

    URL = '/api/tracks/upload-folder/'

    def _audio(self, name, payload):
        return SimpleUploadedFile(name, payload, content_type='audio/mpeg')

    def test_uploads_several_tracks_at_once(self):
        response = self.client.post(self.URL, {
            'files': [
                self._audio('one.mp3', b'first track'),
                self._audio('two.flac', b'second track'),
            ],
        })

        self.assertEqual(response.status_code, 201)
        counts = response.json()['counts']
        self.assertEqual(counts['created'], 2)
        self.assertEqual(Track.objects.count(), 2)

    def test_skips_non_audio_without_failing_the_batch(self):
        # The point of the endpoint: cover art alongside music is normal, and
        # must not be reported as a failure.
        response = self.client.post(self.URL, {
            'files': [
                self._audio('song.mp3', b'real track'),
                SimpleUploadedFile('cover.jpg', b'\xff\xd8\xff', 'image/jpeg'),
                SimpleUploadedFile('.DS_Store', b'junk', 'application/octet-stream'),
            ],
        })

        counts = response.json()['counts']
        self.assertEqual(counts['created'], 1)
        self.assertEqual(counts['skipped'], 2)
        self.assertEqual(counts['failed'], 0)
        self.assertEqual(Track.objects.count(), 1)

    def test_reports_each_file_individually(self):
        response = self.client.post(self.URL, {
            'files': [
                self._audio('song.mp3', b'a track'),
                SimpleUploadedFile('cover.jpg', b'\xff\xd8\xff', 'image/jpeg'),
            ],
        })

        results = {r['name']: r['status'] for r in response.json()['results']}
        self.assertEqual(results['song.mp3'], 'created')
        self.assertEqual(results['cover.jpg'], 'skipped')

    def test_identical_content_is_a_duplicate_not_a_new_track(self):
        payload = b'the very same bytes'
        response = self.client.post(self.URL, {
            'files': [
                self._audio('album/track.mp3', payload),
                self._audio('copy.mp3', payload),
            ],
        })

        counts = response.json()['counts']
        self.assertEqual(counts['created'], 1)
        self.assertEqual(counts['duplicate'], 1)
        self.assertEqual(Track.objects.count(), 1)

    def test_uploaded_track_is_immediately_streamable_by_digest(self):
        # The whole point of ingesting: the PCM server must be able to find it.
        payload = b'freshly uploaded bytes'
        self.client.post(self.URL, {'files': [self._audio('new.mp3', payload)]})

        digest = hashlib.sha256(payload).hexdigest()
        self.assertIsNotNone(resolver.find_track(digest))

    def test_no_files_is_a_bad_request(self):
        response = self.client.post(self.URL, {})
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json())

    def test_get_is_rejected(self):
        self.assertEqual(self.client.get(self.URL).status_code, 405)


class ClearLibraryTests(TempMediaMixin, TestCase):
    """The settings page's 'clear song database' action."""

    URL = '/api/library/clear/'

    def _make_track(self, name, payload):
        return Track.objects.create(
            file=SimpleUploadedFile(name, payload, content_type='audio/mpeg'),
            original_filename=name,
            title=name,
            file_size=len(payload),
            mime_type='audio/mpeg',
            sha256=hashlib.sha256(payload).hexdigest(),
        )

    def setUp(self):
        self.tracks = [
            self._make_track('one.mp3', b'first'),
            self._make_track('two.mp3', b'second'),
        ]

    def test_deletes_every_row(self):
        response = self.client.post(self.URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['deleted'], 2)
        self.assertEqual(Track.objects.count(), 0)

    def test_deletes_the_files_too(self):
        # A bulk queryset delete would drop the rows and orphan these files.
        storage = self.tracks[0].file.storage
        names = [track.file.name for track in self.tracks]
        for name in names:
            self.assertTrue(storage.exists(name))

        self.client.post(self.URL)

        for name in names:
            self.assertFalse(storage.exists(name), f'{name} was left behind')

    def test_clearing_an_empty_library_is_harmless(self):
        self.client.post(self.URL)
        response = self.client.post(self.URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['deleted'], 0)

    def test_get_cannot_clear_the_library(self):
        # A destructive action must not be reachable by navigating to a URL.
        response = self.client.get(self.URL)

        self.assertEqual(response.status_code, 405)
        self.assertEqual(Track.objects.count(), 2)

    def test_csrf_is_enforced(self):
        # Unlike the upload endpoints, this one is not csrf_exempt.
        csrf_client = self.client_class(enforce_csrf_checks=True)
        response = csrf_client.post(self.URL)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Track.objects.count(), 2)


class SettingsPageTests(TempMediaMixin, TestCase):
    def test_page_renders_with_the_clear_button(self):
        response = self.client.get('/settings/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Clear Song Library')
        self.assertContains(response, 'id="clear-library"')
        self.assertContains(response, 'id="clear-modal"')
        self.assertContains(response, 'csrfmiddlewaretoken')

    def test_button_is_disabled_when_there_is_nothing_to_clear(self):
        response = self.client.get('/settings/')
        self.assertContains(response, 'Library is already empty')

    def test_page_reports_the_track_count(self):
        payload = b'a track'
        Track.objects.create(
            file=SimpleUploadedFile('x.mp3', payload, content_type='audio/mpeg'),
            original_filename='x.mp3',
            file_size=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
        )

        response = self.client.get('/settings/')
        self.assertEqual(response.context['track_count'], 1)
        self.assertContains(response, 'Clear song database')

    def test_sidebar_links_to_settings(self):
        response = self.client.get('/')
        self.assertContains(response, 'href="/settings/"')
