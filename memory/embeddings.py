# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Utility to load and retrieve the embedding model.
"""
# pylint: disable=import-error
from sentence_transformers import SentenceTransformer

# Silence harmless "UNEXPECTED" weight loading reports from transformers
try:
    import transformers.utils.logging as tf_logging
    tf_logging.set_verbosity_error()
except ImportError:
    pass

MODEL = None


def get_model():
    """
    Returns the SentenceTransformer model, loading it if necessary.
    """
    global MODEL  # pylint: disable=global-statement

    if MODEL is None:
        print("Loading embedding model once...")
        MODEL = SentenceTransformer("all-MiniLM-L6-v2")

    return MODEL
