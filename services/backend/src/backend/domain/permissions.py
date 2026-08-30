"""RBAC vocabulary — the `Permission` enum and the static role→permission map.

Pure (no third-party imports). Authorization only: a `Permission` answers *may this
role do X*. Tenant isolation (*may this user touch this school's rows*) is a separate
query-layer concern (decisions/0024). Every runtime check routes through the
`PermissionResolver` port (`domain/ports.py`); `ROLE_PERMISSIONS` is the data the
v1 `StaticPermissionResolver` serves. The enum is seeded from the locked product
surface (decisions/0022) and grows per feature phase.
"""

from __future__ import annotations

from enum import StrEnum

from backend.domain.models import Role


class Permission(StrEnum):
    SCHOOL_MANAGE = "school:manage"  # platform_admin: onboard + list schools
    STAFF_MANAGE = "staff:manage"  # school_admin: create + list teachers
    STUDENT_MANAGE = "student:manage"  # admin + teacher: manage students
    EVENT_MANAGE = "event:manage"  # admin + teacher: create + edit events
    MEDIA_UPLOAD = "media:upload"  # admin + teacher: upload event media
    JOB_STATUS_VIEW = "job:status:view"  # admin + teacher: watch processing
    GALLERY_VIEW_ALL = "gallery:view_all"  # admin + teacher: all students' photos
    GALLERY_VIEW_OWN = "gallery:view_own"  # student: only their own photos
    DASHBOARD_VIEW = "dashboard:view"  # admin + teacher: the school command center
    NOTIFICATION_SEND = "notification:send"  # admin + teacher: announce photos to students
    MATCH_REVIEW = "match:review"  # admin + teacher: confirm/reject/add face matches
    AUDIT_VIEW = "audit:view"  # school_admin: read the download/access audit
    CLASS_MANAGE = "class:manage"  # school_admin: create/edit/delete classes (BP11a)
    WHATSAPP_MANAGE = "whatsapp:manage"  # school_admin: configure WhatsApp sending (W1)
    WHATSAPP_SEND = "whatsapp:send"  # admin + teacher: send a student their photos (W2)


# Hardcoded v1 policy. A later DbPermissionResolver overlays per-school overrides
# without touching call sites (decisions/0024). Keep in sync with the Role enum.
ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.PLATFORM_ADMIN: frozenset({Permission.SCHOOL_MANAGE}),
    Role.SCHOOL_ADMIN: frozenset(
        {
            Permission.STAFF_MANAGE,
            Permission.STUDENT_MANAGE,
            Permission.EVENT_MANAGE,
            Permission.MEDIA_UPLOAD,
            Permission.JOB_STATUS_VIEW,
            Permission.GALLERY_VIEW_ALL,
            Permission.DASHBOARD_VIEW,
            Permission.NOTIFICATION_SEND,
            Permission.MATCH_REVIEW,
            # BP8b: the access/download audit is admin-only for now. Granting it to
            # teachers later is a one-line addition to the TEACHER set below.
            Permission.AUDIT_VIEW,
            # BP11a: class (student-group) lifecycle is admin-only, like audit:view. The
            # day-to-day student↔class assignment rides on student:manage (both roles).
            Permission.CLASS_MANAGE,
            # W1: WhatsApp config is admin-only (like audit:view / class:manage). Granting it
            # to teachers later is a one-line addition to the TEACHER set below.
            Permission.WHATSAPP_MANAGE,
            # W2: sending a student their photos over WhatsApp is granted to BOTH school_admin
            # and teacher (mirrors notification:send — both roles distribute photos).
            Permission.WHATSAPP_SEND,
        }
    ),
    Role.TEACHER: frozenset(
        {
            Permission.STUDENT_MANAGE,
            Permission.EVENT_MANAGE,
            Permission.MEDIA_UPLOAD,
            Permission.JOB_STATUS_VIEW,
            Permission.GALLERY_VIEW_ALL,
            Permission.DASHBOARD_VIEW,
            Permission.NOTIFICATION_SEND,
            Permission.MATCH_REVIEW,
            # W2: teachers send a student their photos over WhatsApp too (like notification:send).
            Permission.WHATSAPP_SEND,
        }
    ),
    Role.STUDENT: frozenset({Permission.GALLERY_VIEW_OWN}),
}
