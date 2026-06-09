#!/bin/sh
set -e

echo "Container starting with Application=$APPLICATION_NAME"

export PYTHONPATH=/opt/app

if [ "$APPLICATION_NAME" = "root-password-manager" ]; then
    echo "Running root password manager"
    exec python pyfiles/hyperion_core/root_password_manager.py
elif [ "$APPLICATION_NAME" = "cluster-metadata-exporter" ]; then
    echo "Running cluster metadata exporter"
    exec python pyfiles/hyperion_core/cluster_metadata_exporter.py
elif [ "$APPLICATION_NAME" = "admin-grant-manager" ]; then
    echo "Running admin grant manager"
    exec python pyfiles/hyperion_core/admin_grant_manager.py
else
    echo "Running main.py"
    exec python main.py
fi

