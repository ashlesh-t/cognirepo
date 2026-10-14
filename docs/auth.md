# Auth Guide

> **Legacy:** the JWT/REST API this page described was removed. CogniRepo now has no network login.

The only HTTP surface is the loopback-only control API started by `cognirepo ui`, which authenticates with a
per-session random token (URL fragment → `httpOnly; SameSite=Strict` cookie, or `Authorization: Bearer`).
See [UI_API.md](UI_API.md#authentication).
