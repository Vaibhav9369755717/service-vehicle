# service-vehicle

## Create Login Accounts

The login page supports `admin`, `customer`, and `mechanic` accounts. New public registrations are customers; create staff accounts with the Flask CLI:

```bash
python -m flask --app smart_vehicle_service.app create-user
```

The command prompts for the name, email, role, and password. Use `admin`, `customer`, or `mechanic` for the role. From inside `smart_vehicle_service/`, use `python -m flask --app app create-user` instead.