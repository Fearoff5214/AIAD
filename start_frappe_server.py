import subprocess
import os
import sys

def run_server():
    """Start the Fearoff AIAD Frappe stack using Docker‑Compose.
    The script assumes it is located in the same directory as the
    `docker-compose.yml` file.
    """
    cwd = os.path.abspath(os.path.dirname(__file__))
    try:
        # Bring up the containers in detached mode
        print("Starting Docker‑Compose stack ...")
        subprocess.run(["docker", "compose", "up", "-d"], cwd=cwd, check=True)
        print("\nStack is up. Access the site at http://localhost:8085 (or your LAN IP).")
        print("\nTailing container logs (press Ctrl‑C to stop)...\n")
        # Follow logs for all services
        subprocess.run(["docker", "compose", "logs", "-f"], cwd=cwd)
    except subprocess.CalledProcessError as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(e.returncode)

if __name__ == "__main__":
    run_server()
