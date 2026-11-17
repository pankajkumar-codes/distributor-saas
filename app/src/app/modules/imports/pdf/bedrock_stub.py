"""Placeholder for a paid reader (Claude on AWS Bedrock). Not registered, no AWS call, no spend: Pankaj's
decision D2 is the free reader for now. It exists so the interface is proved to fit a reader that
sends pages elsewhere; switching it on needs his approval."""

from .interface import Limits, ReadResult


class BedrockReader:
    id = "pdf_bedrock_v1"

    def read(self, pdf: bytes, limits: Limits) -> ReadResult:
        raise NotImplementedError("the paid reader is not built; see decision D2")
