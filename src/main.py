"""Dependency-free UDP responder that replies with the sender's address.

Every incoming datagram is answered with ``ip:port`` of the sender, plus an
optional reverse-DNS hostname in parentheses when resolution succeeds.

Usage:
    python main.py [--host HOST] [--port PORT] [--ipv6]
                         [--resolve-names | --no-resolve-names]
                         [--resolver-timeout SECONDS] [--quiet]
"""

from __future__ import annotations

import argparse
import logging
import signal
import socket
import sys
import threading
from typing import Optional, Tuple

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 9999
MAX_DATAGRAM = 2048

log = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "MAX_DATAGRAM",
    "format_reply",
    "resolve_hostname",
    "UDPServer",
    "parse_args",
    "main",
]


def format_reply(address: Tuple[str, int], hostname: Optional[str] = None) -> str:
    """Format a reply string for a peer address.

    Args:
        address: ``(ip, port)`` tuple (extra IPv6 tuple items are ignored).
        hostname: Optional reverse-DNS hostname to append in parentheses.

    Returns:
        ``'ip:port'`` or ``'ip:port (hostname)'`` when a non-empty
        hostname is supplied.
    """
    try:
        ip = str(address[0])
        port = int(address[1])
    except (IndexError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid address {address!r}: {exc}") from exc
    if not ip:
        raise ValueError(f"invalid empty IP in address {address!r}")
    if not 0 <= port <= 65535:
        raise ValueError(f"invalid port {port!r} in address {address!r}")
    if hostname:
        cleaned = str(hostname).strip().rstrip(".").strip()
        if cleaned:
            return f"{ip}:{port} ({cleaned})"
    return f"{ip}:{port}"


def resolve_hostname(ip: str, timeout: float = 0.5) -> Optional[str]:
    """Best-effort reverse-DNS lookup with a hard timeout.

    Runs :func:`socket.gethostbyaddr` in a daemon thread so a stalled
    resolver can never block the serve loop longer than ``timeout``.

    Args:
        ip: IP address string to resolve.
        timeout: Maximum seconds to wait. Non-positive values mean
            "do not attempt" and return ``None`` immediately.

    Returns:
        The primary hostname, or ``None`` on any failure or timeout.
    """
    if not ip or not isinstance(ip, str):
        return None
    try:
        timeout_value = float(timeout)
    except (TypeError, ValueError):
        return None
    if timeout_value <= 0:
        return None
    result: list = []

    def _lookup() -> None:
        try:
            result.append(socket.gethostbyaddr(ip)[0])
        except Exception:  # noqa: BLE001 - any DNS failure maps to None
            result.append(None)

    thread = threading.Thread(target=_lookup, name="reverse-dns", daemon=True)
    thread.start()
    thread.join(timeout_value)
    if thread.is_alive() or not result:
        return None
    value = result[0]
    if not value or not isinstance(value, str):
        return None
    value = value.strip().rstrip(".").strip()
    return value or None


class UDPServer:
    """UDP socket owner that answers every datagram with the peer address."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        family: int = socket.AF_INET,
        resolve_names: bool = True,
        resolver_timeout: float = 0.5,
    ) -> None:
        if family not in (socket.AF_INET, socket.AF_INET6):
            raise ValueError(f"unsupported socket family: {family!r}")
        try:
            port_int = int(port)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid port {port!r}: {exc}") from exc
        if not 0 <= port_int <= 65535:
            raise ValueError(f"port out of range: {port_int}")
        if not isinstance(host, str) or not host:
            raise ValueError(f"invalid host: {host!r}")
        try:
            resolver_timeout_value = float(resolver_timeout)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid resolver_timeout {resolver_timeout!r}: {exc}") from exc
        if resolver_timeout_value < 0:
            raise ValueError("resolver_timeout must be >= 0")

        self.host = host
        self.port = port_int
        self.family = family
        self.resolve_names = bool(resolve_names)
        self.resolver_timeout = resolver_timeout_value
        self._shutdown = threading.Event()
        self._closed = False
        self._lock = threading.Lock()

        try:
            sock = socket.socket(family, socket.SOCK_DGRAM)
        except OSError as exc:
            raise OSError(f"could not create UDP socket: {exc}") from exc
        try:
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            except OSError:
                pass
            sock.settimeout(0.2)
            sock.bind((host, port_int, 0, 0) if family == socket.AF_INET6 else (host, port_int))
        except OSError as exc:
            try:
                sock.close()
            except OSError:
                pass
            raise OSError(f"could not bind UDP {host}:{port_int}: {exc}") from exc
        self.socket = sock

    @property
    def address(self) -> Tuple[str, int]:
        """Actually bound ``(ip, port)`` (real port when port 0 was used)."""
        try:
            name = self.socket.getsockname()
        except OSError:
            return (self.host, self.port)
        try:
            return (str(name[0]), int(name[1]))
        except (IndexError, TypeError, ValueError):
            return (self.host, self.port)

    def serve_forever(self) -> None:
        """Loop on recvfrom and reply until :meth:`shutdown` or close."""
        while not self._shutdown.is_set():
            try:
                data, peer = self.socket.recvfrom(MAX_DATAGRAM)
            except socket.timeout:
                continue
            except OSError:
                # Socket closed (shutdown/close) -> clean exit, no traceback.
                break
            except ValueError:
                # Socket closed concurrently.
                break
            try:
                # Tolerate empty / malformed payloads: content is ignored.
                _ = data  # payload intentionally unused; reply is the peer address
                try:
                    ip = str(peer[0])
                    peer_port = int(peer[1])
                except (IndexError, TypeError, ValueError):
                    log.warning("ignoring datagram from malformed peer %r", peer)
                    continue
                hostname: Optional[str] = None
                if self.resolve_names:
                    try:
                        hostname = resolve_hostname(ip, self.resolver_timeout)
                    except Exception:  # noqa: BLE001 - never break serve loop
                        hostname = None
                try:
                    reply = format_reply((ip, peer_port), hostname)
                except ValueError:
                    log.warning("ignoring datagram with invalid peer %r", peer)
                    continue
                try:
                    self.socket.sendto(reply.encode("utf-8"), peer)
                except OSError as exc:
                    log.warning("sendto %r failed: %s", peer, exc)
                    continue
                log.info("reply %r to %s:%s", reply, ip, peer_port)
            except Exception as exc:  # noqa: BLE001 - keep serving
                log.warning("error handling datagram: %s", exc)
                continue

    def shutdown(self) -> None:
        """Signal the serve loop to stop. Idempotent."""
        self._shutdown.set()

    def close(self) -> None:
        """Close the socket. Idempotent."""
        self._shutdown.set()
        with self._lock:
            if self._closed:
                return
            self._closed = True
        try:
            try:
                self.socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.socket.close()
        except OSError:
            pass

    def __enter__(self) -> "UDPServer":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.shutdown()
        self.close()
        return False


def parse_args(argv=None) -> argparse.Namespace:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        description="UDP server that replies with the sender's ip:port.",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"interface to bind (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port to bind; 0 = ephemeral (default: {DEFAULT_PORT})")
    parser.add_argument("--ipv6", action="store_true", help="use an IPv6 socket (default host becomes '::')")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--resolve-names", dest="resolve_names", action="store_true", help="append reverse-DNS hostname when available (default)")
    group.add_argument("--no-resolve-names", dest="resolve_names", action="store_false", help="disable reverse-DNS lookups")
    parser.set_defaults(resolve_names=True)
    parser.add_argument(
        "--resolver-timeout",
        type=float,
        default=0.5,
        help="max seconds per reverse-DNS lookup (default: 0.5)",
    )
    parser.add_argument("--quiet", action="store_true", help="only log warnings and errors")
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("--port must be in range 0-65535")
    if args.resolver_timeout < 0:
        parser.error("--resolver-timeout must be >= 0")
    return args


def main(argv=None) -> int:
    """CLI entry point. Returns process exit code."""
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    family = socket.AF_INET6 if args.ipv6 else socket.AF_INET
    host = args.host
    if args.ipv6 and host == DEFAULT_HOST:
        host = "::"
    try:
        server = UDPServer(
            host=host,
            port=args.port,
            family=family,
            resolve_names=args.resolve_names,
            resolver_timeout=args.resolver_timeout,
        )
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    bound_ip, bound_port = server.address
    print(f"Listening on {bound_ip}:{bound_port} (udp)", flush=True)
    log.info("Listening on %s:%s (udp) resolve_names=%s", bound_ip, bound_port, args.resolve_names)

    def _handle_signal(signum, frame):  # noqa: ANN001, ANN202
        server.shutdown()

    for sig in (signal.SIGINT, getattr(signal, "SIGTERM", None)):
        if sig is None:
            continue
        try:
            signal.signal(sig, _handle_signal)
        except (OSError, ValueError, RuntimeError):
            pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
    finally:
        server.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())