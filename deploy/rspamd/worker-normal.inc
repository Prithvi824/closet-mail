# Expose the scanner worker on all container interfaces so the processor can reach it.
bind_socket = "*:11333";
# Only accept message bodies over HTTP; never let a client make rspamd read local files.
allow_file_and_shm_inputs = false;
