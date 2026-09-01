from fastapi import Header, HTTPException, status


def _parse_positive_int_header(raw_value: str, header_name: str) -> int:
    try:
        value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid {header_name}: must be an integer",
        ) from exc
    if value <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid {header_name}: must be a positive integer",
        )
    return value


async def get_tenant_id(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> int:
    return _parse_positive_int_header(x_tenant_id, "X-Tenant-ID")


async def get_user_id(x_user_id: str = Header(..., alias="X-User-ID")) -> int:
    return _parse_positive_int_header(x_user_id, "X-User-ID")


def enforce_user_match(authenticated_user_id: int, requested_user_id: int) -> None:
    if authenticated_user_id != requested_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: X-User-ID does not match requested user",
        )
