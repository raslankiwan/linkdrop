"""Reject links and live connections that point at private or loopback networks."""
import ipaddress
import socket
from urllib.parse import urlparse

def public_url(url):
    if not isinstance(url, str) or len(url) > 4096: raise ValueError('Enter a valid link.')
    p = urlparse(url)
    if p.scheme not in ('https', 'http') or not p.hostname or p.username or p.password or p.port not in (None, 80, 443):
        raise ValueError('Use a public HTTP or HTTPS link on a standard port.')
    addresses = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == 'https' else 80), type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('Local and private network addresses are not supported.')
    return url

_installed = False

def protect_network():
    """Check every real connection, which also covers redirects and DNS rebinding."""
    global _installed
    if _installed: return
    original = socket.socket.connect
    def connect(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            host, port = address[:2]
            entries = socket.getaddrinfo(host, port, family=sock.family, type=socket.SOCK_STREAM)
            if not entries or any(not ipaddress.ip_address(item[4][0]).is_global for item in entries):
                raise OSError('Private network connections are blocked.')
            address = entries[0][4]
        return original(sock, address)
    socket.socket.connect = connect
    _installed = True
