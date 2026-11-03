# PostgreSQL is hosted as a container directly on the VM (infra/docker/sweet-spot/docker-compose.prod.yml)
# This eliminates regional quota bottlenecks in indiasouthcentral, provides <0.1ms query latency,
# and saves ~15-25 USD/month of Azure for Students credit.
