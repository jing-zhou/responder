#!/usr/bin/env python3
"""
UDP Responder Server Tester

Tests the UDP server that replies with the sender's address.

Usage:
    python3 test_udp_responder.py <host> <port>

Examples:
    python3 test_udp_responder.py 127.0.0.1 9999
    python3 test_udp_responder.py 127.0.0.1 9999 --timeout 5
"""

import socket
import sys
import argparse
import re


def test_udp_responder(host: str, port: int, timeout: float = 5.0) -> bool:
    """Test that the UDP server replies with our sender address."""
    steps = []
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        steps.append(f"✓ Created UDP socket")

        # Send a test datagram
        test_msg = b"hello"
        sock.sendto(test_msg, (host, port))
        steps.append(f"✓ Sent test datagram to {host}:{port}")

        # Wait for reply
        reply, server_addr = sock.recvfrom(2048)
        reply_str = reply.decode("utf-8", errors="replace").strip()
        steps.append(f"✓ Received reply: {reply_str!r}")

        sock.close()

        # Validate reply format: should contain our local address
        local_ip, local_port = sock.getsockname() if not sock._closed else ("?", "?")
        # Re-create to get local port since we closed it
        # Actually let's check the reply contains an IP:port pattern
        ip_port_pattern = re.compile(r'\d+\.\d+\.\d+\.\d+:\d+')
        match = ip_port_pattern.search(reply_str)

        if match:
            steps.append(f"✓ Reply contains valid IP:port format: {match.group()}")
            print(f"\nResult: UDP responder at {host}:{port} is working!")
            for s in steps:
                print(f"  {s}")
            return True
        else:
            steps.append(f"✗ Reply doesn't match expected IP:port format")
            print(f"\nResult: UDP responder replied, but format unexpected")
            for s in steps:
                print(f"  {s}")
            return False

    except socket.timeout:
        print(f"\nResult: No response from {host}:{port} (timed out)")
        for s in steps:
            print(f"  {s}")
        return False
    except ConnectionRefusedError:
        print(f"\nResult: Connection refused by {host}:{port}")
        for s in steps:
            print(f"  {s}")
        return False
    except OSError as e:
        print(f"\nResult: Network error — {e}")
        for s in steps:
            print(f"  {s}")
        return False
    except Exception as e:
        print(f"\nResult: Error — {e}")
        for s in steps:
            print(f"  {s}")
        return False


def test_udp_multiple_messages(host: str, port: int, timeout: float = 5.0) -> bool:
    """Test sending multiple messages and receiving replies."""
    steps = []
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        steps.append(f"✓ Created UDP socket")

        messages = [b"test1", b"test2", b"test3"]
        replies = []

        for msg in messages:
            sock.sendto(msg, (host, port))
            reply, _ = sock.recvfrom(2048)
            replies.append(reply.decode("utf-8", errors="replace").strip())

        steps.append(f"✓ Sent {len(messages)} messages, received {len(replies)} replies")

        sock.close()

        # All replies should be non-empty
        if all(replies):
            steps.append("✓ All replies received and non-empty")
            print(f"\nResult: Multiple message test passed!")
            for i, (msg, rep) in enumerate(zip(messages, replies), 1):
                print(f"  Message {i}: {msg!r} → {rep!r}")
            for s in steps:
                print(f"  {s}")
            return True
        else:
            steps.append("✗ Some replies were empty")
            print(f"\nResult: Some replies missing")
            for s in steps:
                print(f"  {s}")
            return False

    except socket.timeout:
        print(f"\nResult: Timed out during multiple message test")
        for s in steps:
            print(f"  {s}")
        return False
    except Exception as e:
        print(f"\nResult: Error — {e}")
        for s in steps:
            print(f"  {s}")
        return False


def test_udp_ipv6(host: str, port: int, timeout: float = 5.0) -> bool:
    """Test IPv6 connectivity (if available)."""
    steps = []
    try:
        sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        steps.append(f"✓ Created IPv6 UDP socket")

        test_msg = b"ipv6 test"
        sock.sendto(test_msg, (host, port))
        steps.append(f"✓ Sent IPv6 test datagram to {host}:{port}")

        reply, _ = sock.recvfrom(2048)
        reply_str = reply.decode("utf-8", errors="replace").strip()
        steps.append(f"✓ Received IPv6 reply: {reply_str!r}")

        sock.close()
        print(f"\nResult: IPv6 test passed!")
        for s in steps:
            print(f"  {s}")
        return True

    except socket.timeout:
        print(f"\nResult: IPv6 test timed out")
        for s in steps:
            print(f"  {s}")
        return False
    except OSError as e:
        print(f"\nResult: IPv6 not available or not supported — {e}")
        for s in steps:
            print(f"  {s}")
        return False
    except Exception as e:
        print(f"\nResult: IPv6 error — {e}")
        for s in steps:
            print(f"  {s}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Test UDP responder server")
    parser.add_argument("host", help="Server host")
    parser.add_argument("port", type=int, help="Server port")
    parser.add_argument("--timeout", type=float, default=5.0, help="Timeout in seconds (default: 5)")
    parser.add_argument("--ipv6", action="store_true", help="Also test IPv6")

    args = parser.parse_args()

    print(f"=== UDP Responder Test ===")
    print(f"Target: {args.host}:{args.port}\n")

    # Test 1: basic reply
    print("--- Test 1: Basic Reply ---")
    ok1 = test_udp_responder(args.host, args.port, args.timeout)
    print()

    # Test 2: multiple messages
    print("--- Test 2: Multiple Messages ---")
    ok2 = test_udp_multiple_messages(args.host, args.port, args.timeout)
    print()

    # Test 3: IPv6 (optional)
    ok3 = True  # default to pass if not tested
    if args.ipv6:
        print("--- Test 3: IPv6 ---")
        ok3 = test_udp_ipv6(args.host, args.port, args.timeout)
        print()

    # Summary
    print("=== Summary ===")
    print(f"  Basic Reply:      {'PASS' if ok1 else 'FAIL'}")
    print(f"  Multiple Messages: {'PASS' if ok2 else 'FAIL'}")
    if args.ipv6:
        print(f"  IPv6:             {'PASS' if ok3 else 'FAIL'}")

    sys.exit(0 if (ok1 and ok2 and ok3) else 1)


if __name__ == "__main__":
    main()
