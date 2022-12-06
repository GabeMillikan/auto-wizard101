from wizard101.central import remote

# pull data from wizard101central
# This will take a *long* time on the first run, but will be much faster on subsequent runs.
# You can omit this check if you believe your cached database is up-to-date.
remote.refresh_item_index()
