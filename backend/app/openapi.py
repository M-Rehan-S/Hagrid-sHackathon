"""OpenAPI/Swagger configuration shared by the Flask app."""

from spectree import SecurityScheme, SpecTree
from spectree.models import InType, SecureType, SecuritySchemeData


spec = SpecTree(
    "flask",
    title="Relief Claim Copilot API",
    version="1.0.0",
    path="apidocs",
    mode="greedy",
    security_schemes=[
        SecurityScheme(
            name="BearerAuth",
            data=SecuritySchemeData(
                type=SecureType.HTTP,
                scheme="bearer",
                bearer_format="JWT",
            ),
        ),
        SecurityScheme(
            name="APIKeyAuth",
            data=SecuritySchemeData(
                type=SecureType.API_KEY,
                name="X-API-Key",
                field_in=InType.HEADER,
            ),
        ),
    ],
)
