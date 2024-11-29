-- create empty tables

CREATE TABLE accounts (
    id VARCHAR(255) PRIMARY KEY,
    type VARCHAR(255),
    display_name VARCHAR(255),
    account_type VARCHAR(255),
    ownership_type VARCHAR(255),
    balance NUMERIC,
    currency VARCHAR(255),
    value_str VARCHAR(255),
    value_base INTEGER,
    created_at TIMESTAMP
);

CREATE TABLE transactions (
    id VARCHAR(255) PRIMARY KEY,
    account_id VARCHAR(255),
    status VARCHAR(255),
    raw_text VARCHAR(255),
    description VARCHAR(255),
    message VARCHAR(255),
    categorizable BOOLEAN,
    currency VARCHAR(255),
    value_str VARCHAR(255),
    value_base INTEGER,
    card_purchase_suffix VARCHAR(255),
    settled_at TIMESTAMP,
    created_at TIMESTAMP,
   CONSTRAINT fk_accounts
      FOREIGN KEY(account_id) 
        REFERENCES accounts(id)
);

-- copy production to a test database
CREATE DATABASE test
WITH TEMPLATE postgres
OWNER postgres;