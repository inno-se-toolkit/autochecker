"""IP address validation for student VM IPs."""

import re

IP_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")


def validate_ip(ip: str) -> tuple[bool, str | None]:
    """Validate a VM IP address.

    Returns (True, None) if valid, or (False, error_message) if invalid.
    """
    if not IP_RE.match(ip):
        return False, (
            "That doesn't look like a valid IP address.\n"
            "Please send just the IP (e.g., <code>10.93.25.100</code>):"
        )

    octets = [int(o) for o in ip.split(".")]
    if any(o > 255 for o in octets):
        return False, (
            "Invalid IP address — each octet must be 0-255.\n"
            "Please enter a valid IP:"
        )

    # Reject reserved/dummy addresses
    if (
        ip == "0.0.0.0"
        or ip == "255.255.255.255"
        or octets[0] == 127          # loopback
        or octets[0] >= 224          # multicast + reserved
        or (octets[0] == 169 and octets[1] == 254)  # link-local
    ):
        return False, (
            "This is a reserved IP address and cannot be used.\n"
            "Please enter your actual VM IP:"
        )

    # Internal 10.x.x.x — must be 10.93.x.x
    if octets[0] == 10:
        if octets[1] != 93:
            return False, (
                "Internal IPs must be from the <b>10.93.x.x</b> subnet.\n\n"
                'VMs under the "Software Engineering Toolkit" subscription '
                "are created in the 10.93.x.x network. If your VM has a "
                "different subnet, it was created under a different subscription. "
                'Please create your VM under the "Software Engineering Toolkit" '
                "subscription."
            )

    return True, None
