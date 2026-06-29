"""Inference worker entrypoint (scaffold).

The real loop will: consume an InferenceJob, build a job context (thresholds
resolved once per job), call InferenceService.process(), ack/nack with retry and
dead-letter handling. For now this is a placeholder so the worker image has a
command to run.
"""


def main() -> None:
    print("ml-service inference worker: scaffold — no job loop yet")


if __name__ == "__main__":
    main()
