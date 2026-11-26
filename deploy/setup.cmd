@echo off
rem Wrapper so the PowerShell script runs without changing the machine execution policy.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
