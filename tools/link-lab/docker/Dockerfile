# build_docker.py first builds the repository-root Ares image, then extends it.
ARG ARES_IMAGE=smk-link-ares:latest
FROM ${ARES_IMAGE}
ARG JOBS=4
COPY asar /tmp/asar
RUN cmake -S /tmp/asar/src -B /tmp/asar-build -DCMAKE_BUILD_TYPE=Release \
    && cmake --build /tmp/asar-build -j "$JOBS" \
    && install /tmp/asar-build/asar/asar-standalone /usr/local/bin/asar \
    && rm -rf /tmp/asar /tmp/asar-build
COPY disassembly /opt/disassembly
COPY entrypoint.py /opt/build-rom.py
RUN chmod -R a+rX /opt/disassembly && chmod a+r /opt/build-rom.py
ENTRYPOINT ["python3", "/opt/build-rom.py"]
