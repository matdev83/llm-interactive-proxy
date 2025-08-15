#!/usr/bin/env python
"""
Restart the LLM Interactive Proxy service.

This script provides utility functions for restarting the proxy service
in various deployment environments.
"""

import argparse
import logging
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import List, Optional


def setup_logging() -> None:
    """Set up basic logging."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def is_windows() -> bool:
    """Check if the current platform is Windows."""
    return platform.system() == "Windows"


def restart_systemd_service(service_name: str) -> bool:
    """Restart a systemd service.
    
    Args:
        service_name: The name of the service to restart
        
    Returns:
        True if successful, False otherwise
    """
    logging.info(f"Restarting systemd service: {service_name}")
    try:
        # Check if service exists
        result = subprocess.run(
            ["systemctl", "status", service_name],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 and "could not be found" in result.stderr:
            logging.error(f"Service {service_name} does not exist")
            return False
        
        # Restart the service
        result = subprocess.run(
            ["sudo", "systemctl", "restart", service_name],
            capture_output=True,
            text=True,
            check=False,
        )
        
        if result.returncode != 0:
            logging.error(f"Failed to restart service: {result.stderr}")
            return False
        
        logging.info(f"Service {service_name} restarted successfully")
        return True
    
    except Exception as e:
        logging.error(f"Error restarting service: {str(e)}")
        return False


def restart_docker_container(container_name: str) -> bool:
    """Restart a Docker container.
    
    Args:
        container_name: The name of the container to restart
        
    Returns:
        True if successful, False otherwise
    """
    logging.info(f"Restarting Docker container: {container_name}")
    try:
        # Check if container exists
        result = subprocess.run(
            ["docker", "ps", "-a", "--filter", f"name={container_name}", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            check=True,
        )
        
        if not result.stdout.strip():
            logging.error(f"Container {container_name} does not exist")
            return False
        
        # Restart the container
        result = subprocess.run(
            ["docker", "restart", container_name],
            capture_output=True,
            text=True,
            check=False,
        )
        
        if result.returncode != 0:
            logging.error(f"Failed to restart container: {result.stderr}")
            return False
        
        logging.info(f"Container {container_name} restarted successfully")
        return True
    
    except Exception as e:
        logging.error(f"Error restarting container: {str(e)}")
        return False


def restart_windows_service(service_name: str) -> bool:
    """Restart a Windows service.
    
    Args:
        service_name: The name of the service to restart
        
    Returns:
        True if successful, False otherwise
    """
    logging.info(f"Restarting Windows service: {service_name}")
    try:
        # Check if service exists
        result = subprocess.run(
            ["sc", "query", service_name],
            capture_output=True,
            text=True,
            check=False,
        )
        
        if "The specified service does not exist" in result.stderr:
            logging.error(f"Service {service_name} does not exist")
            return False
        
        # Stop the service
        subprocess.run(
            ["net", "stop", service_name],
            capture_output=True,
            check=False,
        )
        
        # Start the service
        result = subprocess.run(
            ["net", "start", service_name],
            capture_output=True,
            text=True,
            check=False,
        )
        
        if result.returncode != 0:
            logging.error(f"Failed to restart service: {result.stderr}")
            return False
        
        logging.info(f"Service {service_name} restarted successfully")
        return True
    
    except Exception as e:
        logging.error(f"Error restarting service: {str(e)}")
        return False


def restart_dev_server() -> bool:
    """Restart the development server.
    
    Returns:
        True if successful, False otherwise
    """
    logging.info("Restarting development server")
    try:
        # Find uvicorn processes
        if is_windows():
            # Windows approach
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq python.exe"],
                capture_output=True,
                text=True,
                check=True,
            )
            
            # Find uvicorn PIDs
            import re
            pids = []
            for line in result.stdout.splitlines():
                if "python.exe" in line and "uvicorn" in line:
                    match = re.search(r"python\.exe\s+(\d+)", line)
                    if match:
                        pids.append(match.group(1))
            
            # Kill processes
            for pid in pids:
                subprocess.run(["taskkill", "/F", "/PID", pid], check=False)
        else:
            # Unix approach
            subprocess.run(
                ["pkill", "-f", "uvicorn"],
                capture_output=True,
                check=False,
            )
        
        # Start the server
        script_dir = Path(__file__).resolve().parent.parent.parent
        app_module = "src.main:app"
        
        cmd = [
            "uvicorn", 
            app_module, 
            "--host", "0.0.0.0",
            "--port", "8000",
            "--reload",
        ]
        
        if is_windows():
            # On Windows, start in a new window
            subprocess.Popen(
                cmd,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
                cwd=script_dir,
            )
        else:
            # On Unix, start in the background
            subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=script_dir,
            )
        
        logging.info("Development server restarted successfully")
        return True
    
    except Exception as e:
        logging.error(f"Error restarting development server: {str(e)}")
        return False


def main(args: Optional[List[str]] = None) -> int:
    """Main entry point.
    
    Args:
        args: Command line arguments
        
    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    setup_logging()
    
    parser = argparse.ArgumentParser(description="Restart the LLM Interactive Proxy service")
    
    # Define target service type options as a mutually exclusive group
    service_type = parser.add_mutually_exclusive_group(required=True)
    service_type.add_argument(
        "--systemd",
        metavar="SERVICE_NAME",
        help="Restart a systemd service (Linux)",
        default=None,
    )
    service_type.add_argument(
        "--docker",
        metavar="CONTAINER_NAME",
        help="Restart a Docker container",
        default=None,
    )
    service_type.add_argument(
        "--windows",
        metavar="SERVICE_NAME",
        help="Restart a Windows service",
        default=None,
    )
    service_type.add_argument(
        "--dev",
        action="store_true",
        help="Restart the development server",
        default=False,
    )
    
    # Parse arguments
    parsed_args = parser.parse_args(args)
    
    # Handle the restart based on the specified type
    success = False
    
    if parsed_args.systemd:
        if is_windows():
            logging.error("Cannot restart systemd services on Windows")
            return 1
        success = restart_systemd_service(parsed_args.systemd)
    
    elif parsed_args.docker:
        success = restart_docker_container(parsed_args.docker)
    
    elif parsed_args.windows:
        if not is_windows():
            logging.error("Cannot restart Windows services on non-Windows platforms")
            return 1
        success = restart_windows_service(parsed_args.windows)
    
    elif parsed_args.dev:
        success = restart_dev_server()
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
