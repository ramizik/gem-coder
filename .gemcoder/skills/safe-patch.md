# safe-patch

Use this skill when producing code changes.

1. Keep the patch small and directly tied to the requested task.
2. Avoid unrelated refactors or formatting churn.
3. Preserve public behavior unless the task requires a behavioral change.
4. Do not touch secrets, generated files, local caches, or unrelated tool output.
5. Return a unified diff plus a short summary.
