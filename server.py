import os
import asyncio
import signal


class UDPServerProtocol(asyncio.DatagramProtocol):
    def __init__(self):
        self.transport = None

    def connection_made(self, transport: asyncio.DatagramTransport):
        """Called once when the UDP socket is bound and ready."""
        self.transport = transport
        host, port = transport.get_extra_info('sockname')
        print(f"UDP server listening on {host}:{port}")

    def datagram_received(self, data: bytes, addr: tuple[str, int]):
        """Called every time a UDP packet arrives."""
        client_ip, client_port = addr

        try:
            message = data.decode('utf-8').strip()
            print(f"Received from {client_ip}:{client_port} -> {message}")

            # Include the sender's IP and port in the response
            response = f"ACK from {client_ip}:{client_port} | Message: {message}".encode('utf-8')
            self.transport.sendto(response, addr)

        except UnicodeDecodeError:
            print(f"Received non-UTF8 binary data ({len(data)} bytes) from {client_ip}:{client_port}")

    def error_received(self, exc: Exception):
        """Called when a send or receive operation raises an OSError."""
        print(f"Socket error received: {exc}")

    def connection_lost(self, exc: Exception | None):
        """Called when the socket is closed."""
        print("UDP server socket closed.")


class UDPServerApp:
    def __init__(self, host: str = '0.0.0.0', port: int = 9999):
        self.host = host
        self.port = port
        self.transport = None
        self.protocol = None

    async def start(self):
        """Starts the UDP server and waits for shutdown signals."""
        loop = asyncio.get_running_loop()

        self.transport, self.protocol = await loop.create_datagram_endpoint(
            lambda: UDPServerProtocol(),
            local_addr=(self.host, self.port)
        )

        stop_event = asyncio.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except NotImplementedError:
                pass

        try:
            await stop_event.wait()
        finally:
            print("\nShutting down server...")
            self.transport.close()

    def run(self):
        """Synchronous top-level entry point to run the server."""
        try:
            asyncio.run(self.start())
        except KeyboardInterrupt:
            pass

    def __call__(self):
        """Allows the app instance itself to be called directly like app()."""
        self.run()


# Uses 'fly-global-services' on Fly.io, falls back to '0.0.0.0' locally
bind_host = os.getenv("UDP_HOST", "0.0.0.0")
app = UDPServerApp(host=bind_host, port=9999)

if __name__ == "__main__":
    app.run()
