<div align="center">
  <h1>👋 Hi, I'm Zaac</h1>
  <h3>Broadcast Engineer | Systems Architect | Edge Computing Enthusiast</h3>
</div>

---

I build highly resilient, low-latency architectures for live production environments, pushing the boundaries of what's possible with WebRTC, NDI, and decentralized edge computing. My work bridges the gap between traditional AV broadcasting (OBS, Ontime) and modern distributed systems.

### 🛠️ Core Technologies & Focus Areas
- **Live Video & Audio Transmission**: `LiveKit`, `WebRTC`, `NDI`, `Sonobus`
- **Broadcast Orchestration**: `OBS Studio`, `Ontime`, `Patchbay` architectures
- **Distributed Computing & Storage**: `Rclone`, Federated Storage (`EchoMesh`), Stateless Edge Workers
- **Agentic & AI Workflows**: Building safe, pure-rule execution engines that interface with AI agents

### 🚀 Featured Projects & Architecture

#### 📡 The Broadcast Ecosystem
*   **[LiveView Broadcast Monitor](https://github.com/ZaacIsHere/LiveView-Broadcast-Monitor-v0.2)**: An advanced WebRTC multiview dashboard designed for live control rooms. Features WHIP Ingress for OBS integration, Egress routing, and NDI bridging capabilities.
*   **[Gallery](https://github.com/ZaacIsHere/gallery)**: A strict, pure-rule broadcast orchestrator and execution engine. It consumes normalized state buses (like Patchbay) and dispatches audited intents to live gear (OBS, Ontime) via a hardened executor.
*   **[ProStage Timer](https://github.com/ZaacIsHere/ProStage-Timer)**: A real-time collaborative stage timing and cue management application built on Socket.io and WebRTC, ensuring zero-drift synchronization across all show callers and downstage monitors.

#### ☁️ The Edge Cloud Ecosystem
*   **[Cloud Mesh Kit](https://github.com/ZaacIsHere/Cloud-Mesh-Kit)**: A decentralized "swarm" toolkit that networks together fragmented cloud storage tiers (Nextcloud, Dropbox, SMB) into a unified logical volume using `rclone union`.
*   **[Nexus Mesh (EchoMesh)](https://github.com/ZaacIsHere/Nexus-Mesh-EchoMesh-Cloud-Array)**: A custom-built federated storage orchestrator that chunks large files (2MB shards) across REST APIs and rebuilds them via HTTP Range requests. Roadmapped for Reed-Solomon Erasure Coding and End-to-End Encryption.
*   **[Compute-PoC-Worker](https://github.com/ZaacIsHere/Compute-PoC-Worker)**: A stateless swarm compute node that leverages free-tier GitHub Actions to poll tasks, execute payloads, and immutably persist results to Hugging Face datasets.

#### 🧠 The Agentic Ecosystem
*   **[mnemex](./mnemex)**: A zero-dependency memory + knowledge base system for Claude. Pairs a spec-exact, path-hardened implementation of Anthropic's memory tool (`memory_20250818`) with a just-in-time BM25 knowledge base (`kb_search`) and server-side context editing for ~84% token savings on long runs. Portable storage backends (local / in-memory / git-sync) let a stateless worker persist its entire memory to git or a Hugging Face dataset and rehydrate on the next run.

---

<div align="center">
  <i>"Move fast and break stuff is fun for prototypes, but measure twice and cut once is for for production."</i>
</div>
