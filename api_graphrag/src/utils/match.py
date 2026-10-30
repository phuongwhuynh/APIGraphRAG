def match_param(code_param: str, openapi_params: list[str]) -> bool:
    # Remove trailing [] for array parameters in OpenAPI
    for openapi_param in openapi_params:
        normalized_openapi = openapi_param.rstrip("[]")
        if code_param == normalized_openapi:
            return True
    return False