# Separate verifier image. Harbor runs /tests/test.sh here after the agent's
# container and the env server are stopped. It only reads the evidence that the
# collect hook pulled out of the env server (/srv/pinbox/out).
FROM @@BASE_IMAGE@@

COPY . /tests/
RUN chmod 0755 /tests/test.sh
