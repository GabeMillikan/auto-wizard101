import wizard101.central as w101central


# pull data from wizard101central
# This will take a *long* time on the first run, but will be much faster on subsequent runs.
# You can omit this check if you believe your cached database is up-to-date.
# w101central.remote.refresh_item_index()

if __name__ == "__main__":
    w101central.processor.main()
