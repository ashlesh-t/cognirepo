import os


def init_project():
    os.makedirs(".cognirepo/memory", exist_ok=True)
    os.makedirs(".cognirepo/docs", exist_ok=True)

    print("Cognirepo initialized.")