import logging

def setup_custom_logger(name, log_file):
    formatter = logging.Formatter('-%(levelname)s- %(asctime)s : %(message)s')

    ## Logfile handler
    file_handler = logging.FileHandler(log_file, mode='w')
    file_handler.setLevel(logging.INFO)
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

