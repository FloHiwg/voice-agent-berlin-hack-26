# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Phase 4: Tool Calling for State Management**
  - `retrieve_case_data` tool: Query insurance case database by phone number or claim ID
    - Loads existing case data at session start
    - Automatically populates state with customer info, incident details, and third-party information
    - Mock database with sample cases for testing
  - `update_case_status` tool: Update case status based on caller input
    - Validates status against allowed values (pending_details, documentation_required, assessment_in_progress, approved, rejected, settled, closed, under_review)
    - Case-insensitive status updates
    - Returns validation errors with list of valid statuses
  - Real-time state capture and persistence
    - Agent extracts data from each user response via `update_claim_state` tool
    - All 27 playbook required fields supported
    - Supports partial information capture with follow-up support
    - Dot-notation keys for nested field updates (customer.*, incident.*, damage.*, etc.)
    - List normalization (comma-separated values converted to arrays)
  - State persistence and reconnection
    - State saved immediately to JSON storage after each update
    - Session state survives connection drops
    - Previous session state loaded on reconnect
  - System prompt integration
    - Shows current collected fields and missing fields per playbook stage
    - Prevents agent from re-asking previously answered questions
    - Guides agent to next missing field based on playbook
  - Comprehensive test coverage (11 passing tests)
- Added FIELD_VALIDATION_REPORT documenting full alignment between playbook fields, tool calling, and system prompt

## [0.1.0] - 2024-04-25

- Initial release with Phase 3 implementation
- Identity verification with OR logic
- Caller verification and conditional stages
- Playbook engine with evaluation runner
