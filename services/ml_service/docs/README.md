# ML Service — Design Docs

Living design documentation with diagrams, built phase by phase alongside the
code. The binding specs are the repo-root `ml-service-requirements.md` (the
"what") and `ml-service-architecture.md` (the "how"); the rationale for choices
made while building lives in the repo-root `decisions/` log.

| Doc | Covers | Phase |
|---|---|---|
| [01-domain.md](01-domain.md) | Domain models, the 9 ports, decision logic, errors | 1 |
| [02-adapters.md](02-adapters.md) | Adapter/library table + conventions (component diagram) | 2 |
| [03-pipelines.md](03-pipelines.md) | Enrollment + inference flows (sequence diagrams) | 1 |
| [05-data-model.md](05-data-model.md) | Postgres schema / ER diagram (req §10) | 2 |
| [06-faiss-lifecycle.md](06-faiss-lifecycle.md) | FAISS read/write-path diagrams (architecture §7) | 2 |

Docs for the API, the worker, deployment, and observability land with their
phases (04, 07–09).

> Diagrams are [Mermaid](https://mermaid.js.org/); they render on GitHub and in
> VS Code with a Mermaid extension.
