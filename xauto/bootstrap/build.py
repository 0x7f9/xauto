#!/usr/bin/env python3

import os
import sys
import subprocess
import logging
import platform

BOOTSTRAP_DIR = os.path.dirname(__file__)
GET_PIP_PATH = os.path.join(BOOTSTRAP_DIR, "get-pip.py")
LIB_DIR = os.path.normpath(os.path.join(BOOTSTRAP_DIR, ".."))
INSTALLS_FILE = os.path.join(BOOTSTRAP_DIR, "installs.txt")
VENV_DIR = os.path.join(BOOTSTRAP_DIR, "venv")

IS_WINDOWS = platform.system() == "Windows"
if IS_WINDOWS:
    PYTHON_EXE = os.path.join(VENV_DIR, "Scripts", "python.exe")
    PIP_EXE = os.path.join(VENV_DIR, "Scripts", "pip.exe")
else:
    PYTHON_EXE = os.path.join(VENV_DIR, "bin", "python")
    PIP_EXE = os.path.join(VENV_DIR, "bin", "pip")

BOOTSTRAP_LOG = os.path.join(BOOTSTRAP_DIR, "bootstrap.log")
BOOTSTRAP_DONE_MARKER = os.path.join(BOOTSTRAP_DIR, ".bootstrap_done")

GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"

def setup_bootstrap_logger():
    logger = logging.getLogger('bootstrap')
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        handler = logging.FileHandler(BOOTSTRAP_LOG)
        formatter = logging.Formatter('%(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger


def get_pip():
    logger = setup_bootstrap_logger()
    
    if os.path.exists(GET_PIP_PATH):
        logger.info("Using existing get-pip.py")
        return True

    logger.info(f"Downloading get-pip.py from {GET_PIP_URL}")
    print(f"Downloading get-pip.py from {GET_PIP_URL}")
    
    try:
        subprocess.run(
            ["curl", "-sSL", GET_PIP_URL, "-o", GET_PIP_PATH],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        if os.path.exists(GET_PIP_PATH):
            logger.info("Downloaded get-pip.py using curl")
            return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        logger.info("curl not available, trying urllib")
    
    try:
        import urllib.request
        urllib.request.urlretrieve(GET_PIP_URL, GET_PIP_PATH)
        logger.info("Downloaded get-pip.py using urllib")
        return os.path.exists(GET_PIP_PATH)
    except Exception as e:
        logger.error(f"Failed to download get-pip.py: {e}")
        return False


def is_in_venv():
    if not (hasattr(sys, 'real_prefix') or 
            (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)):
        return False
    
    try:
        return os.path.samefile(sys.executable, PYTHON_EXE)
    except (OSError, FileNotFoundError):
        return False


def is_venv_functional():
    if not os.path.exists(VENV_DIR):
        return False
    
    if not os.path.exists(PYTHON_EXE):
        return False
    
    try:
        # this hardcodes a package name, this might effect users if not inside installs.txt
        result = subprocess.run([PYTHON_EXE, "-c", "import requests"], 
                              capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError):
        return False


def create_venv():
    logger = setup_bootstrap_logger()
    
    if os.path.exists(VENV_DIR):
        logger.info(f"Using existing virtual environment at {VENV_DIR}")
        return True
    
    logger.info(f"Creating virtual environment at {VENV_DIR}")
    try:
        subprocess.run([sys.executable, "-m", "venv", VENV_DIR], 
                      check=True, capture_output=True, text=True)
        logger.info("Virtual environment created successfully")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to create virtual environment: {e}")
        if e.stderr:
            logger.error(f"stderr: {e.stderr}")
        return False


def install_pip():
    logger = setup_bootstrap_logger()
    
    if os.path.exists(PIP_EXE):
        logger.info("pip already installed in virtual environment")
        return True
        
    if not get_pip():
        logger.error(f"get-pip.py not found at {GET_PIP_PATH} and could not download it")
        return False
    
    logger.info("Installing pip using bundled get-pip.py")
    try:
        subprocess.run([PYTHON_EXE, GET_PIP_PATH, "--quiet", "--no-warn-script-location"], 
                      check=True, capture_output=True, text=True)
        logger.info("pip installed successfully")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to install pip: {e}")
        if e.stderr:
            logger.error(f"stderr: {e.stderr}")
        return False


def install_packages():
    logger = setup_bootstrap_logger()
    if not os.path.exists(INSTALLS_FILE):
        logger.warning(f"installs.txt not found at {INSTALLS_FILE}")
        return True
    
    if not os.path.exists(PIP_EXE):
        logger.error("pip not available for package installation")
        return False
    
    logger.info("Installing required packages...")
    try:
        subprocess.run([PIP_EXE, "install", "--disable-pip-version-check", "--no-cache-dir", "-r", INSTALLS_FILE], 
                                check=True, capture_output=True, text=True)
        logger.info("Package installation completed")
        print("Package installation completed")
        return True
        
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to install packages: {e}")
        if e.stderr:
            logger.error(f"stderr: {e.stderr}")
        return False


def bootstrap_venv():
    if is_in_venv():
        if is_venv_functional():
            return True
        else:
            print("ERROR: Currently in virtual environment but it's not functional.")
            print("Run `python lib/bootstrap/cleanup_bootstrap.py` to rebuild the venv.")
            sys.exit(1)
    
    if os.path.exists(BOOTSTRAP_DONE_MARKER) and is_venv_functional():
        print("Bootstrap marker exists and venv is functional, switching to it...")
        try:
            os.execv(PYTHON_EXE, [PYTHON_EXE] + sys.argv)
        except OSError as e:
            print(f"Failed to re-execute script: {e}")
            sys.exit(1)
    
    print("Setting up virtual environment...")
    
    if not create_venv():
        print("Failed to create virtual environment")
        sys.exit(1)
    
    if not install_pip():
        print("Failed to install pip")
        sys.exit(1)
    
    if not install_packages():
        print("Failed to install packages")
        sys.exit(1)
    
    with open(BOOTSTRAP_DONE_MARKER, "w") as f:
        f.write("ok\n")
    
    try:
        os.execv(PYTHON_EXE, [PYTHON_EXE] + sys.argv)
    except OSError as e:
        print(f"Failed to re-execute script: {e}")
        sys.exit(1)


def cleanup_bootstrap():
    print("Cleaning up bootstrap state")
    
    try:
        if os.path.exists(BOOTSTRAP_DONE_MARKER):
            os.remove(BOOTSTRAP_DONE_MARKER)
            print("Removed bootstrap marker")

        if os.path.exists(VENV_DIR):
            import shutil
            shutil.rmtree(VENV_DIR)
            print("Removed virtual environment")

        if os.path.exists(BOOTSTRAP_LOG):
            os.remove(BOOTSTRAP_LOG)
            print("Removed bootstrap log")

        # if os.path.exists(GET_PIP_PATH):
        #     os.remove(GET_PIP_PATH)
        #     print("Removed get-pip.py")

    except OSError as e:
        print(f"Failed to cleanup environment: {e}")


def bootstrap():
    if is_in_venv() and is_venv_functional():
        from xauto.utils.config import Config
        from xauto.utils.setup import check_python_version, download_geckodriver
        check_python_version(Config.get("misc.python_version", "3.10"))
        download_geckodriver(Config.get("misc.geckodriver_version", "0.35.0"))
        return True

    if is_in_venv() and not is_venv_functional():
        print("In virtual environment but not functional, rebuilding...")
        cleanup_bootstrap()
        bootstrap_venv()
        # should never be reached
        return False

    if not is_in_venv():
        # print(f"Not in virtual environment, switching to it...")
        bootstrap_venv()
        # should never be reached
        return False
        
    return False

