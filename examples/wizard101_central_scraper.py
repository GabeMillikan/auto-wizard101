from wizard101.central import remote


with open("download-log.txt", "a") as log_file:
    for retry in range(5):
        remote.load_item_page_sources(log_file)
