import json, threading, unittest, urllib.request, sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
from lib.engine import public_url
from http.server import ThreadingHTTPServer

class BackendTests(unittest.TestCase):
    def test_local_clear_keeps_active_jobs_and_files(self):
        app=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        thread=threading.Thread(target=app.serve_forever,daemon=True);thread.start()
        old=server.JOBS.copy()
        try:
            server.JOBS.clear();server.JOBS.update({'done':{'status':'complete'},'failed':{'status':'error'},'active':{'status':'downloading'}})
            req=urllib.request.Request(f'http://127.0.0.1:{app.server_port}/api/history/clear',data=b'{}',headers={'X-Token':server.TOKEN,'Content-Type':'application/json'})
            with urllib.request.urlopen(req) as response: result=json.load(response)
            self.assertEqual(result,{'cleared':2});self.assertEqual(list(server.JOBS),['active'])
        finally:
            server.JOBS.clear();server.JOBS.update(old);app.shutdown();app.server_close()
    def test_cloud_rejects_private_addresses_and_non_web_links(self):
        for url in ['http://127.0.0.1/x','http://169.254.169.254/x','http://[::1]/x','file:///etc/passwd','https://user:pass@example.com/x','https://example.com:8080/x']:
            with self.subTest(url=url),self.assertRaises(ValueError):public_url(url)
    def test_cloud_rejects_dns_names_resolving_to_private_network(self):
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('10.0.0.1',80))]):
            with self.assertRaises(ValueError):public_url('http://example.com/x')

if __name__=='__main__':unittest.main()

class YouTubeRecoveryTests(unittest.TestCase):
    def test_youtube_verification_has_recovery_code(self):
        from lib.errors import download_error
        result=download_error("ERROR: [youtube] S-WLYzKZiDg: Sign in to confirm you’re not a bot. Use --cookies")
        self.assertEqual(result['code'],'YOUTUBE_AUTH_REQUIRED')
        self.assertIn('local Mac app',result['error'])
        self.assertNotIn('--cookies',result['error'])
    def test_other_errors_are_not_misclassified(self):
        from lib.errors import download_error
        self.assertEqual(download_error('Video unavailable')['code'],'DOWNLOAD_FAILED')
    def test_browser_auth_is_opt_in_and_allowlisted(self):
        self.assertNotIn('cookiesfrombrowser',server.options())
        self.assertEqual(server.options('chrome')['cookiesfrombrowser'],('chrome',))
        with self.assertRaises(ValueError):server.options('/arbitrary/path')
