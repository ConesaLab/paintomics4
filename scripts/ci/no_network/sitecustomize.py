"""Refuse every outbound network connection that is not loopback.

Put this directory first on PYTHONPATH and the interpreter imports it at
start-up (site.py loads `sitecustomize`). From then on any attempt to open a
TCP/UDP connection to a host other than the loopback interface -- rest.kegg.jp,
reactome.org, the LLM gateway, PubMed, Europe PMC, anything -- raises
OSError with a message naming the host, instead of silently reaching the
internet from a CI job.

The point is not to make such tests pass; it is to make a test that depends on
an external service FAIL LOUDLY in CI so it gets a stub, and to guarantee that
the jobs that declare "no secrets, nothing external" cannot be wrong about it.

Loopback is allowed because the services CI starts for itself (MongoDB, stub
HTTP servers used by the AI-pipeline tests) listen there. Extra hosts can be
allowed with PAINTOMICS_CI_ALLOW_HOSTS="host1,host2" -- never set that in a
workflow that is supposed to run offline.
"""
import os
import socket

_ALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "::", ""}
_ALLOWED_HOSTS.update(
    host.strip() for host in os.environ.get("PAINTOMICS_CI_ALLOW_HOSTS", "").split(",")
    if host.strip())


def _host_of(address):
    if isinstance(address, (tuple, list)) and address:
        return str(address[0])
    if isinstance(address, (str, bytes)):
        return ""          # AF_UNIX path: local by definition
    return str(address)


def _is_loopback(host):
    if host in _ALLOWED_HOSTS:
        return True
    if host.startswith("127.") or host.startswith("::ffff:127."):
        return True
    if host.lower().startswith("localhost"):
        return True
    return False


def _refuse(host):
    raise OSError(
        "outbound network is disabled in this job (sitecustomize: "
        "scripts/ci/no_network); refused connection to %r" % host)


_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex


def _guarded_connect(self, address):
    host = _host_of(address)
    if not _is_loopback(host):
        _refuse(host)
    return _real_connect(self, address)


def _guarded_connect_ex(self, address):
    host = _host_of(address)
    if not _is_loopback(host):
        _refuse(host)
    return _real_connect_ex(self, address)


socket.socket.connect = _guarded_connect
socket.socket.connect_ex = _guarded_connect_ex

_real_getaddrinfo = socket.getaddrinfo


def _guarded_getaddrinfo(host, *args, **kwargs):
    name = host.decode() if isinstance(host, bytes) else (host or "")
    if not _is_loopback(name):
        _refuse(name)
    return _real_getaddrinfo(host, *args, **kwargs)


socket.getaddrinfo = _guarded_getaddrinfo
