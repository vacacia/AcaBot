<system-reminder name="workspace_restrictions">

## Workspace Restrictions

All of your work, file reads/writes, operations, and modifications **MUST be strictly confined within the `/workspace` directory**.

- Do not interact with or modify any files outside of this boundary unless a dedicated maintenance tool explicitly handles that for you.
- **Why this matters**: Only the `/workspace` directory is connected to the external environment (e.g., shared with NapCat). This means any files—such as images, audio, or other media—that you intend to send to the user MUST be generated and saved inside `/workspace`. If you save a file outside of this directory, external services will be completely unable to access or transmit it.
- If a dedicated install/maintenance tool is available, keep your editable or downloaded artifacts in `/workspace`, then use that tool to publish them into the runtime-managed location.

</system-reminder>
