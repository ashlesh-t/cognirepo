"""
Module to initialize the cognirepo project structure.
"""
import os


def init_project():
    """
    Create the necessary directory structure for cognirepo.
    """
    os.makedirs(".cognirepo/memory", exist_ok=True)
    os.makedirs(".cognirepo/docs", exist_ok=True)

    print("Cognirepo initialized.")
