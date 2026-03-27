# SPDX-FileCopyrightText: © 2025 Tenstorrent AI ULC
# SPDX-License-Identifier: Apache-2.0

import logging

def setup_custom_logger(name, log_file):
    formatter = logging.Formatter('-%(levelname)s- %(asctime)s : %(message)s')

    ## Logfile handler - captures DEBUG and above so that "Running command" details
    ## are always recorded even when the console only shows INFO.
    file_handler = logging.FileHandler(log_file, mode='w')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO) # Different level possible
    console_handler.setFormatter(formatter)

    ## now set up the message logger
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG) # Set the minimum log level
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger

