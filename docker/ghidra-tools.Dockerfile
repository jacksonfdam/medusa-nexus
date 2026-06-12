# MEDUSA NEXUS — ghidra-tools image.
# The binary engines too heavy to bundle in the app: Ghidra headless, jadx,
# apktool — plus the JRE they all need. Built once in CI, pushed to GHCR,
# pulled by the app at first boot. Linux/amd64 + arm64.
#
# Build:  docker buildx build -f docker/ghidra-tools.Dockerfile \
#           --platform linux/amd64,linux/arm64 \
#           -t ghcr.io/jacksonfdam/medusa-nexus/ghidra-tools:$TAG --push .

FROM eclipse-temurin:17-jre-jammy

ARG GHIDRA_VERSION=11.1.2
ARG GHIDRA_DATE=20240709
ARG JADX_VERSION=1.5.0
ARG APKTOOL_VERSION=2.9.3

ENV GHIDRA_HOME=/opt/ghidra \
    PATH="/opt/ghidra/support:/opt/jadx/bin:/opt/apktool:${PATH}"

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl unzip bash python3 \
    && rm -rf /var/lib/apt/lists/*

# ── Ghidra headless ──
RUN curl -fsSL -o /tmp/ghidra.zip \
      "https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_${GHIDRA_VERSION}_build/ghidra_${GHIDRA_VERSION}_PUBLIC_${GHIDRA_DATE}.zip" \
    && unzip -q /tmp/ghidra.zip -d /opt \
    && mv /opt/ghidra_${GHIDRA_VERSION}_PUBLIC /opt/ghidra \
    && rm /tmp/ghidra.zip

# ── jadx ──
RUN curl -fsSL -o /tmp/jadx.zip \
      "https://github.com/skylot/jadx/releases/download/v${JADX_VERSION}/jadx-${JADX_VERSION}.zip" \
    && mkdir -p /opt/jadx && unzip -q /tmp/jadx.zip -d /opt/jadx && rm /tmp/jadx.zip

# ── apktool ──
RUN mkdir -p /opt/apktool \
    && curl -fsSL -o /opt/apktool/apktool.jar \
      "https://github.com/iBotPeaches/Apktool/releases/download/v${APKTOOL_VERSION}/apktool_${APKTOOL_VERSION}.jar" \
    && curl -fsSL -o /opt/apktool/apktool \
      "https://raw.githubusercontent.com/iBotPeaches/Apktool/master/scripts/linux/apktool" \
    && chmod +x /opt/apktool/apktool

WORKDIR /workspace
