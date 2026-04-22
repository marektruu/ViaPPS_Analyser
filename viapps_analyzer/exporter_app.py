from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from viapps_analyzer.exporter_core import ExporterConfig, estimate_directory_workload, export_overview_dataset, find_latest_config, load_exporter_config


class ExporterApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("ViaPPS Exporter")
        self.root.geometry("760x560")

        self.message_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.current_config_path: Path | None = None

        self.config_path_var = tk.StringVar()
        self.input_dir_var = tk.StringVar()
        self.output_dir_var = tk.StringVar()
        self.scan_summary_var = tk.StringVar(value="No config loaded.")
        self.progress_text_var = tk.StringVar(value="Ready.")
        self.summary_var = tk.StringVar(value="")
        self.recursive_var = tk.BooleanVar(value=False)
        self.parquet_var = tk.BooleanVar(value=True)
        self.csv_var = tk.BooleanVar(value=False)
        self.geojson_var = tk.BooleanVar(value=False)

        self._build_ui()
        self._load_latest_config()
        self._poll_queue()

    def _build_ui(self) -> None:
        frame = ttk.Frame(self.root, padding=16)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Config file").grid(row=0, column=0, sticky="w", pady=(0, 8))
        ttk.Entry(frame, textvariable=self.config_path_var).grid(row=0, column=1, sticky="ew", pady=(0, 8))
        ttk.Button(frame, text="Browse", command=self._browse_config).grid(row=0, column=2, padx=(8, 0), pady=(0, 8))
        ttk.Button(frame, text="Reload", command=self._load_selected_config).grid(row=0, column=3, padx=(8, 0), pady=(0, 8))

        ttk.Label(frame, text="Input folder").grid(row=1, column=0, sticky="w", pady=(0, 8))
        ttk.Entry(frame, textvariable=self.input_dir_var).grid(row=1, column=1, sticky="ew", pady=(0, 8))
        ttk.Button(frame, text="Browse", command=self._browse_input_dir).grid(row=1, column=2, padx=(8, 0), pady=(0, 8))

        ttk.Label(frame, text="Output folder").grid(row=2, column=0, sticky="w", pady=(0, 8))
        ttk.Entry(frame, textvariable=self.output_dir_var).grid(row=2, column=1, sticky="ew", pady=(0, 8))
        ttk.Button(frame, text="Browse", command=self._browse_output_dir).grid(row=2, column=2, padx=(8, 0), pady=(0, 8))

        ttk.Checkbutton(frame, text="Include subfolders", variable=self.recursive_var, command=self._refresh_scan_summary).grid(row=3, column=1, sticky="w", pady=(0, 12))

        formats = ttk.LabelFrame(frame, text="Output formats", padding=12)
        formats.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(0, 12))
        ttk.Checkbutton(formats, text="Parquet", variable=self.parquet_var).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(formats, text="CSV", variable=self.csv_var).grid(row=0, column=1, sticky="w", padx=(16, 0))
        ttk.Checkbutton(formats, text="GeoJSON", variable=self.geojson_var).grid(row=0, column=2, sticky="w", padx=(16, 0))

        ttk.Button(frame, text="Estimate workload", command=self._refresh_scan_summary).grid(row=5, column=0, sticky="w", pady=(0, 8))
        ttk.Label(frame, textvariable=self.scan_summary_var, wraplength=700, justify="left").grid(row=5, column=1, columnspan=3, sticky="w", pady=(0, 8))

        self.progress = ttk.Progressbar(frame, mode="determinate")
        self.progress.grid(row=6, column=0, columnspan=4, sticky="ew", pady=(0, 8))
        ttk.Label(frame, textvariable=self.progress_text_var, wraplength=700, justify="left").grid(row=7, column=0, columnspan=4, sticky="w", pady=(0, 16))

        ttk.Button(frame, text="Run", command=self._start_export).grid(row=8, column=0, sticky="w")
        ttk.Label(frame, textvariable=self.summary_var, wraplength=700, justify="left").grid(row=8, column=1, columnspan=3, sticky="w")

    def _load_latest_config(self) -> None:
        latest = find_latest_config(Path(__file__).resolve().parent)
        if latest is not None:
            self.config_path_var.set(str(latest))
            self._load_selected_config()
        else:
            self.scan_summary_var.set("No config file found next to ViaPPS Exporter.")

    def _load_selected_config(self) -> None:
        path_text = self.config_path_var.get().strip()
        if not path_text:
            self.scan_summary_var.set("Choose a config file first.")
            return
        path = Path(path_text)
        if not path.exists():
            messagebox.showerror("ViaPPS Exporter", f"Config file not found:\n{path}")
            return
        config = load_exporter_config(path)
        self.current_config_path = path
        self.input_dir_var.set(config.input_directory)
        self.output_dir_var.set(config.output_directory)
        self.recursive_var.set(bool(config.recursive))
        formats = {fmt.lower() for fmt in config.export_formats}
        self.parquet_var.set("parquet" in formats or not formats)
        self.csv_var.set("csv" in formats)
        self.geojson_var.set("geojson" in formats)
        self._refresh_scan_summary()

    def _browse_config(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("JSON files", "*.json"), ("All files", "*.*")], title="Choose exporter config")
        if path:
            self.config_path_var.set(path)
            self._load_selected_config()

    def _browse_input_dir(self) -> None:
        path = filedialog.askdirectory(title="Choose input folder")
        if path:
            self.input_dir_var.set(path)
            self._refresh_scan_summary()

    def _browse_output_dir(self) -> None:
        path = filedialog.askdirectory(title="Choose output folder")
        if path:
            self.output_dir_var.set(path)

    def _refresh_scan_summary(self) -> None:
        input_dir = self.input_dir_var.get().strip()
        if not input_dir:
            self.scan_summary_var.set("Choose an input folder to estimate the workload.")
            return
        file_count, total_bytes = estimate_directory_workload(input_dir, recursive=self.recursive_var.get())
        total_mb = total_bytes / (1024 * 1024) if total_bytes else 0
        self.scan_summary_var.set(f"Found {file_count} TSV/TXT files, about {total_mb:.1f} MB in total.")

    def _start_export(self) -> None:
        if not self.input_dir_var.get().strip():
            messagebox.showwarning("ViaPPS Exporter", "Choose an input folder first.")
            return
        formats = []
        if self.parquet_var.get():
            formats.append("parquet")
        if self.csv_var.get():
            formats.append("csv")
        if self.geojson_var.get():
            formats.append("geojson")
        if not formats:
            messagebox.showwarning("ViaPPS Exporter", "Choose at least one output format.")
            return

        config = load_exporter_config(self.current_config_path) if self.current_config_path else ExporterConfig()
        config.input_directory = self.input_dir_var.get().strip()
        config.output_directory = self.output_dir_var.get().strip() or config.input_directory
        config.recursive = self.recursive_var.get()
        config.export_formats = formats

        self.progress.configure(value=0, maximum=max(1, estimate_directory_workload(config.input_directory, config.recursive)[0]))
        self.progress_text_var.set("Starting export...")
        self.summary_var.set("")

        worker = threading.Thread(target=self._run_export, args=(config,), daemon=True)
        worker.start()

    def _run_export(self, config: ExporterConfig) -> None:
        def callback(current: int, total: int, message: str) -> None:
            self.message_queue.put(("progress", (current, total, message)))

        try:
            summary = export_overview_dataset(config, progress_callback=callback)
            self.message_queue.put(("done", summary))
        except Exception as exc:
            self.message_queue.put(("error", str(exc)))

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self.message_queue.get_nowait()
                if kind == "progress":
                    current, total, message = payload
                    self.progress.configure(maximum=max(1, total), value=current)
                    self.progress_text_var.set(message)
                elif kind == "done":
                    summary = payload
                    output_list = ", ".join(f"{fmt}: {path}" for fmt, path in summary.output_files.items()) or "No output files created."
                    failed = f" Failed: {len(summary.failed_files)}." if summary.failed_files else ""
                    self.progress.configure(value=self.progress["maximum"])
                    self.progress_text_var.set("Export completed.")
                    self.summary_var.set(
                        f"Processed {summary.processed_files}/{summary.total_files} files.{failed} Outputs: {output_list}"
                    )
                elif kind == "error":
                    self.progress_text_var.set("Export failed.")
                    messagebox.showerror("ViaPPS Exporter", str(payload))
        except queue.Empty:
            pass
        self.root.after(200, self._poll_queue)


def main() -> None:
    root = tk.Tk()
    ttk.Style().theme_use("clam")
    ExporterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
