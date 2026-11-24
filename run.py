import argparse
import sys
import uvicorn
from app.config import HOST, PORT, DEBUG

def main():
    parser = argparse.ArgumentParser(description="DDDS Cloud - Distributed Dual-Display Smart Classroom Platform")
    parser.add_argument("--host", default=HOST, help=f"Host address (default: {HOST})")
    parser.add_argument("--port", type=int, default=PORT, help=f"Port (default: {PORT})")
    parser.add_argument("--reload", action="store_true", default=DEBUG, help="Auto-reload on code change")
    
    args = parser.parse_args()

    print("\n" + "=" * 65)
    print("  DDDS Cloud - Distributed Dual-Display Smart Classroom Platform")
    print(f"  Server ishga tushmoqda: http://localhost:{args.port}")
    print("=" * 65 + "\n")

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info"
    )

if __name__ == "__main__":
    main()

