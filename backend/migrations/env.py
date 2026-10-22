from alembic import context
from sqlalchemy import create_engine
from app.db.models import Base

config = context.config
with create_engine(config.get_main_option("sqlalchemy.url")).connect() as connection:
    connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    connection.commit()
    context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()
