from django.test import TestCase
from django.urls import reverse


class HomePageTests(TestCase):
    def test_home_page_renders(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Better Titan Radio')
        self.assertContains(response, 'Available Tracks')
        self.assertContains(response, 'Stream latency')
        self.assertContains(response, 'Sync a Music Folder')
