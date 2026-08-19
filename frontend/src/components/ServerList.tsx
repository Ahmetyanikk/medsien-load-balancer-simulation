import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  createServer,
  deleteServer,
  listServers,
  updateServer,
  type Server,
  type ServerCreate,
  type ServerUpdate,
} from "../api/client";
import ServerForm from "./ServerForm";

type ListState = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; servers: Server[] };

function messageFor(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

export default function ServerList() {
  const [state, setState] = useState<ListState>({ status: "loading" });
  const [editingId, setEditingId] = useState<string | null>(null);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [mutating, setMutating] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  // Monotonic generation token: whichever refresh() call incremented it last
  // owns the right to write `state`. A call whose captured token no longer
  // matches the current value is stale — from a superseded StrictMode
  // double-invocation or an effect that has since been cleaned up — and its
  // result is discarded rather than applied, regardless of resolution order.
  const generationRef = useRef(0);

  const refresh = useCallback(async () => {
    const token = ++generationRef.current;
    setState({ status: "loading" });
    try {
      const servers = await listServers();
      if (token !== generationRef.current) return; // superseded — do not apply
      setState({ status: "ready", servers });
    } catch (err) {
      if (token !== generationRef.current) return; // superseded — do not apply
      setState({ status: "error", message: messageFor(err, "Unable to load servers.") });
    }
  }, []);

  useEffect(() => {
    void refresh();
    return () => {
      // Invalidate this effect invocation's in-flight request on cleanup (real
      // unmount, or StrictMode's synthetic unmount) so a late response can
      // never apply itself.
      generationRef.current += 1;
    };
  }, [refresh]);

  function openCreateForm() {
    setEditingId(null);
    setFormError(null);
    setShowCreateForm((visible) => !visible);
  }

  function openEditForm(id: string) {
    setShowCreateForm(false);
    setFormError(null);
    setEditingId(id);
  }

  async function handleCreate(values: ServerCreate | ServerUpdate) {
    setMutating(true);
    setFormError(null);
    try {
      await createServer(values as ServerCreate);
      setShowCreateForm(false);
      await refresh();
    } catch (err) {
      setFormError(messageFor(err, "Unable to create server."));
    } finally {
      setMutating(false);
    }
  }

  async function handleUpdate(id: string, values: ServerCreate | ServerUpdate) {
    setMutating(true);
    setFormError(null);
    try {
      await updateServer(id, values as ServerUpdate);
      setEditingId(null);
      await refresh();
    } catch (err) {
      setFormError(messageFor(err, "Unable to update server."));
    } finally {
      setMutating(false);
    }
  }

  async function handleDelete(id: string) {
    if (!window.confirm(`Delete server "${id}"? This cannot be undone.`)) {
      return;
    }
    setMutating(true);
    setDeleteError(null);
    try {
      await deleteServer(id);
      await refresh();
    } catch (err) {
      setDeleteError(messageFor(err, "Unable to delete server."));
    } finally {
      setMutating(false);
    }
  }

  return (
    <section className="panel" aria-labelledby="servers-heading">
      <div className="panel-header">
        <h2 id="servers-heading">Servers</h2>
        <button type="button" onClick={openCreateForm} disabled={mutating || state.status === "loading"}>
          {showCreateForm ? "Close" : "Add server"}
        </button>
      </div>

      {deleteError ? (
        <p role="alert" className="form-error">
          {deleteError}
        </p>
      ) : null}

      {showCreateForm ? (
        <ServerForm
          mode="create"
          initialServer={null}
          submitting={mutating}
          error={formError}
          onSubmit={handleCreate}
          onCancel={() => setShowCreateForm(false)}
        />
      ) : null}

      {state.status === "loading" ? <p>Loading servers…</p> : null}
      {state.status === "error" ? <p role="alert">{state.message}</p> : null}
      {state.status === "ready" && state.servers.length === 0 ? <p>No servers configured.</p> : null}

      {state.status === "ready" && state.servers.length > 0 ? (
        <table>
          <caption className="sr-only">Configured servers</caption>
          <thead>
            <tr>
              <th scope="col">ID</th>
              <th scope="col">CPU / tick</th>
              <th scope="col">Memory (MB)</th>
              <th scope="col">Rate limit / sec</th>
              <th scope="col">Actions</th>
            </tr>
          </thead>
          <tbody>
            {state.servers.map((server) =>
              editingId === server.id ? (
                <tr key={server.id}>
                  <td colSpan={5}>
                    <ServerForm
                      mode="edit"
                      initialServer={server}
                      submitting={mutating}
                      error={formError}
                      onSubmit={(values) => handleUpdate(server.id, values)}
                      onCancel={() => setEditingId(null)}
                    />
                  </td>
                </tr>
              ) : (
                <tr key={server.id}>
                  <td>{server.id}</td>
                  <td>{server.cpu_units_per_tick}</td>
                  <td>{server.mem_mb}</td>
                  <td>{server.rate_limit_per_sec}</td>
                  <td>
                    <button type="button" onClick={() => openEditForm(server.id)} disabled={mutating}>
                      Edit
                    </button>
                    <button type="button" onClick={() => handleDelete(server.id)} disabled={mutating}>
                      Delete
                    </button>
                  </td>
                </tr>
              ),
            )}
          </tbody>
        </table>
      ) : null}
    </section>
  );
}
