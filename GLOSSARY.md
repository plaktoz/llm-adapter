# llm-adapter

An in-process Python library that gives UMAS code one interface for calling LLMs across providers. These terms are the vocabulary of the requirements and the code.

## Language

**Alias**:
A name that a caller uses to pick a model, for example `default`. A config entry maps it to a primary and an optional fallback.
_Avoid_: Model name, model ID

**Provider**:
A configured endpoint that serves models. It has a base URL, a key variable name and a wire format.
_Avoid_: Vendor, backend

**Adapter**:
The code module that maps one wire format to the shared types and classifies its errors.
_Avoid_: Driver, connector

**Primary**:
The first provider and model that an alias tries.
_Avoid_: Main

**Fallback**:
The provider and model that an alias tries after the primary fails. An alias can have none.
_Avoid_: Secondary, backup

**Attempt**:
One call to a provider, with its outcome. A `Response` lists every attempt in order.
_Avoid_: Call, try

**Usage event**:
The report that the library sends to `on_usage` for each attempt. It carries counts and no content.
_Avoid_: Usage record (a record belongs to `token-ledger`)

**Error class**:
A named group of provider failures that share one retry and failover policy.
_Avoid_: Error type

**Caller**:
UMAS code that sends a `Request` to the library.
_Avoid_: Client, consumer
