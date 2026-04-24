# usai-harness Documentation

The documentation is organized as a systems engineering spine. Read in this order on a first pass:

1. **[ADRs](adr/)** — Architecture Decision Records. Each captures one design decision with its context, the decision, and consequences. These are the foundation; every other document refers back to them.

2. **[SRS](srs.md)** — Software Requirements Specification. Functional, security, and interface requirements. Every requirement traces to an ADR.

3. **[NFR](nfr.md)** — Non-Functional Requirements. Quality attributes (performance, reliability, security, portability, maintainability, usability) with acceptance criteria and verification methods.

4. **[Architecture](architecture.md)** — Component diagram, data flow, interface specifications, threat model. How the pieces fit together.

5. **[TEVV Plan](tevv-plan.md)** — Test, Evaluation, Verification, and Validation. How conformance to the SRS and NFR is established.

6. **[RTM](rtm.md)** — Requirements Traceability Matrix. Every requirement mapped to its implementation, test, and evidence. The audit-ready view.

Once the spine is understood, use these as operational references:

7. **[API Reference](api-reference.md)** — Public Python API, CLI, configuration schemas, extension protocols, on-disk artifact formats. For developers writing code against the library.

8. **[Operations Guide](ops-guide.md)** — Setup, key rotation, batch job operations, reporting, adding providers, troubleshooting. For researchers using the library.

The README at the repository root is the entry point for new users. CLAUDE.md covers project conventions for developers modifying the library.
