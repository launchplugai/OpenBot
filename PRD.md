# Openbot Automation Platform - Product Requirements Document

## Overview

Openbot is an automation platform designed to run automated tasks on AWS EC2 instances with SSM-only access. It pulls target repositories, runs tests, writes logs, and produces machine-readable receipt JSON files.

## Core Principles

1. **Automation, not autonomy** - Openbot executes predefined tasks; it does not make autonomous decisions.
2. **Proof artifacts required** - Nothing is successful without logs, test output, and receipt JSON.
3. **Safe failure by default** - No guessing. Fail safely and document errors.
4. **No scope expansion** - No dashboards, no Kubernetes, no "nice-to-have" features.

## Phase 1: Openbot Runtime

### Goals

Implement a minimal Openbot runtime that can:
- Run on AWS EC2 (SSM-only access)
- Pull a target repository
- Run tests
- Write logs
- Write a receipt JSON

### Non-Goals (Phase 1)

- No deploy loop
- No Claude integration
- No auto-triggering beyond manual command
- No infrastructure changes
- No production deployment

### Deliverables

1. **CLI Commands**
   - `openbot doctor` - Health check for runtime environment
   - `openbot run` - Execute test run against target repository

2. **Artifact Generation**
   - Combined log files under `logs/`
   - Receipt JSON under `receipts/`
   - Receipt validation against JSON Schema

3. **Policy Scaffolding**
   - `protected_paths.yaml` - Globs for protected paths
   - `escalation_rules.yaml` - Rules for failure handling

### Exit Criteria (Phase 1)

- [ ] CLI runs on vanilla Ubuntu EC2
- [ ] `openbot doctor` validates environment
- [ ] `openbot run` clones repo, runs tests, writes receipt
- [ ] Receipt JSON validates against schema
- [ ] All runs produce logs and receipts (even on failure)
- [ ] Documentation complete for operations and security

## Receipt Schema (v1)

Every run produces a receipt JSON with:
- `receipt_version`: "v1"
- `timestamp`: UTC ISO8601
- `run_id`: UUID
- `target_repo`, `target_branch`: Repository details
- `commit_sha`: Checked out commit
- `test`: Command, exit code, summary, log path
- `health`: Optional health check results
- `overall_status`: SUCCESS | FAILED
- `errors`: Array of error strings

## Security Model

- No SSH access - SSM only
- No long-lived AWS keys
- Least privilege IAM roles
- Protected paths prevent modification of critical files
- Safe defaults - fail closed, not open
