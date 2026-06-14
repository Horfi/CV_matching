"use client";

import { useState, useEffect, useRef, useCallback } from "react";

interface CVData {
  name: string;
  contact_info: string;
  skills: string[];
  experience: string;
}

interface JobMatch {
  job_id: number;
  title: string;
  company: string;
  description: string;
  url: string;
  skills: string;
  score: number;
}

interface ScrapingSource {
  id: number;
  url: string;
  name: string;
  type: string;
  status: string;
  last_scraped_at: string | null;
  created_at: string | null;
}

interface StateValues {
  user_id?: string;
  cv_data?: CVData;
  matched_jobs?: JobMatch[];
  status?: string;
  human_approved?: boolean;
}

export default function Home() {
  const [file, setFile] = useState<File | null>(null);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [statusText, setStatusText] = useState<string>("Upload your CV to begin matching.");
  const [state, setState] = useState<StateValues | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const [isExtracting, setIsExtracting] = useState(false);
  const [isMatching, setIsMatching] = useState(false);
  const [isApplying, setIsApplying] = useState(false);

  // Scraping States
  const [sources, setSources] = useState<ScrapingSource[]>([]);
  const [selectedSources, setSelectedSources] = useState<number[]>([]);
  const [newSourceUrl, setNewSourceUrl] = useState("");
  const [newSourceName, setNewSourceName] = useState("");
  const [newSourceType, setNewSourceType] = useState("careers_page");
  const [isScraping, setIsScraping] = useState(false);

  // Profile Editor States
  const [extractedCv, setExtractedCv] = useState<CVData | null>(null);

  // Apply Selection States
  const [selectedJobs, setSelectedJobs] = useState<string[]>([]);
  
  const pollingRef = useRef<NodeJS.Timeout | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Fetch Sources on load
  const fetchSources = async () => {
    try {
      const res = await fetch("http://localhost:8000/api/v1/scraping/sources");
      if (res.ok) {
        const data = await res.json();
        setSources(data);
      }
    } catch (err) {
      console.error("Failed to fetch sources", err);
    }
  };

  useEffect(() => {
    fetchSources();
  }, []);

  // Poll status endpoint for matching updates
  useEffect(() => {
    if (!threadId) return;

    const pollStatus = async () => {
      try {
        const res = await fetch(`http://localhost:8000/api/v1/status/${threadId}`);
        if (!res.ok) return;
        
        const data: StateValues = await res.json();
        setState(data);

        // Update status text based on backend state
        if (data.status === "matching") {
          setStatusText("Qdrant is performing semantic search and matching jobs...");
        } else if (data.status?.startsWith("matching_failed")) {
          setStatusText("Failed to find job matches. Make sure Qdrant is seeded.");
          stopPolling();
        } else if (data.status === "matching_complete") {
          setStatusText("Job matching complete! Select matches below to apply.");
          stopPolling();
        } else if (data.status === "review_pending") {
          setStatusText("Awaiting human review to complete application forms.");
          stopPolling();
        } else if (data.status === "submitted") {
          setStatusText("Applications submitted successfully!");
          stopPolling();
        }
      } catch (err) {
        console.error("Polling error:", err);
      }
    };

    // Run first immediately
    pollStatus();
    
    // Set interval
    pollingRef.current = setInterval(pollStatus, 2000);

    return () => stopPolling();
  }, [threadId]);

  const stopPolling = () => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  };

  // Drag and Drop handlers
  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(true);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!e.currentTarget.contains(e.relatedTarget as Node)) {
      setIsDragOver(false);
    }
  };

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
    const dropped = e.dataTransfer.files;
    if (dropped && dropped.length > 0) {
      setFile(dropped[0]);
    }
  }, []);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files;
    if (selected && selected.length > 0) {
      setFile(selected[0]);
    }
  };

  const openFilePicker = () => {
    fileInputRef.current?.click();
  };

  // Extract CV logic (parsing only)
  const extractCvData = async () => {
    if (!file) return;
    setIsExtracting(true);
    setStatusText("Extracting CV information via Gemini...");
    setExtractedCv(null);
    setState(null);
    setThreadId(null);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch("http://localhost:8000/api/v1/extract-cv", {
        method: "POST",
        body: formData,
      });

      if (!res.ok) throw new Error("Extraction failed");

      const data = await res.json();
      setExtractedCv(data);
      setStatusText("CV parsed! Review and edit the profile in the editor.");
    } catch (err) {
      console.error(err);
      setStatusText("Extraction failed. Please verify services are running.");
    } finally {
      setIsExtracting(false);
    }
  };

  // Trigger matching on edited CV data
  const handleMatchJobs = async () => {
    if (!extractedCv) return;
    setIsMatching(true);
    setStatusText("Submitting CV profile for semantic matching...");
    setState(null);
    setThreadId(null);

    try {
      const res = await fetch("http://localhost:8000/api/v1/trigger", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          cv_data: extractedCv,
          source_ids: selectedSources,
        }),
      });

      if (!res.ok) throw new Error("Matching failed");

      const data = await res.json();
      setThreadId(data.thread_id);
    } catch (err) {
      console.error(err);
      setStatusText("Matching failed.");
      setIsMatching(false);
    } finally {
      setIsMatching(false);
    }
  };

  // Source configuration CRUD
  const handleAddSource = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newSourceUrl || !newSourceName) return;

    try {
      const res = await fetch("http://localhost:8000/api/v1/scraping/sources", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: newSourceUrl,
          name: newSourceName,
          type: newSourceType,
        }),
      });

      if (res.ok) {
        setNewSourceUrl("");
        setNewSourceName("");
        fetchSources();
      }
    } catch (err) {
      console.error("Failed to add source", err);
    }
  };

  const toggleSourceSelection = (id: number) => {
    if (selectedSources.includes(id)) {
      setSelectedSources(selectedSources.filter((sid) => sid !== id));
    } else {
      setSelectedSources([...selectedSources, id]);
    }
  };

  const toggleAllSources = () => {
    if (selectedSources.length === sources.length) {
      setSelectedSources([]);
    } else {
      setSelectedSources(sources.map((s) => s.id));
    }
  };

  // Trigger crawler action
  const handleScrapeSelected = async () => {
    if (selectedSources.length === 0) return;
    setIsScraping(true);
    setStatusText("Crawling selected sources for active job offers...");

    try {
      const res = await fetch("http://localhost:8000/api/v1/scraping/scrape-selected", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids: selectedSources }),
      });

      if (res.ok) {
        fetchSources();
        // Poll sources status until all completed or failed
        const interval = setInterval(async () => {
          const checkRes = await fetch("http://localhost:8000/api/v1/scraping/sources");
          if (checkRes.ok) {
            const data: ScrapingSource[] = await checkRes.json();
            setSources(data);
            const stillScraping = data.some((s) => selectedSources.includes(s.id) && s.status === 'scraping');
            if (!stillScraping) {
              clearInterval(interval);
              setIsScraping(false);
              setStatusText("Scraping completed! New jobs indexed in PostgreSQL + Qdrant.");
            }
          }
        }, 2000);
      } else {
        setIsScraping(false);
        setStatusText("Scraping trigger failed.");
      }
    } catch (err) {
      console.error(err);
      setIsScraping(false);
      setStatusText("Scraping failed.");
    }
  };

  // Apply selectors
  const toggleJobSelection = (url: string) => {
    if (selectedJobs.includes(url)) {
      setSelectedJobs(selectedJobs.filter((ju) => ju !== url));
    } else {
      setSelectedJobs([...selectedJobs, url]);
    }
  };

  const toggleAllJobs = () => {
    const matched = state?.matched_jobs || [];
    if (selectedJobs.length === matched.length) {
      setSelectedJobs([]);
    } else {
      setSelectedJobs(matched.map((j) => j.url));
    }
  };

  // Dispatch selective application workers
  const handleApplySelected = async () => {
    if (selectedJobs.length === 0 || !threadId || !extractedCv) return;
    setIsApplying(true);
    setStatusText("Launching automated playbooks for selected jobs...");

    try {
      const res = await fetch("http://localhost:8000/api/v1/apply-selected", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          thread_id: threadId,
          job_urls: selectedJobs,
          cv_data: extractedCv,
        }),
      });

      if (res.ok) {
        setStatusText("Automated applications dispatched! Playwright workers running in the background.");
        setSelectedJobs([]);
      } else {
        setStatusText("Failed to dispatch applications.");
      }
    } catch (err) {
      console.error(err);
      setStatusText("Application dispatch failed.");
    } finally {
      setIsApplying(false);
    }
  };

  return (
    <main className="min-h-screen bg-slate-50 text-slate-800 flex flex-col font-sans relative">
      <header className="border-b border-slate-200 bg-white sticky top-0 z-50 py-4 px-6 md:px-12 flex justify-between items-center relative">
        <div className="flex items-center gap-3">
          <div className="h-9 w-9 rounded-lg bg-slate-900 flex items-center justify-center shadow-sm">
            <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          </div>
          <div>
            <span className="font-bold text-lg text-slate-900 block leading-tight">Antigravity Agent</span>
            <span className="text-[10px] block text-slate-500 font-medium">CV Matcher & Automated Apply</span>
          </div>
        </div>
        <div className="flex items-center gap-2 text-xs bg-slate-100 border border-slate-200 px-3 py-1.5 rounded-lg text-slate-600 font-mono font-medium">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 inline-block" />
          SYSTEM ACTIVE
        </div>
      </header>

      <section className="relative z-10 flex-1 max-w-6xl w-full mx-auto p-6 md:p-12 flex flex-col gap-8">
        
        {/* API Console Notification */}
        <div className="p-4 bg-slate-900 border border-slate-800 rounded-xl text-xs text-slate-300 font-mono flex items-start gap-2.5 leading-relaxed shadow-sm">
          <svg className="w-4 h-4 text-indigo-400 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <span>System Console: {statusText}</span>
        </div>

        {/* Crawler & Source Management Panel (Full Width) */}
        <div className="bg-white border border-slate-200 rounded-xl p-6 md:p-8 shadow-sm flex flex-col gap-6">
          <div className="flex flex-col md:flex-row md:items-center justify-between border-b border-slate-100 pb-4 gap-4">
            <div>
              <h2 className="text-lg font-bold text-slate-900 flex items-center gap-2.5">
                <svg className="w-5 h-5 text-indigo-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9m-9 9a9 9 0 019-9" />
                </svg>
                Manage Scraping Sources & Job Boards
              </h2>
              <p className="text-xs text-slate-500 mt-1">Configure listing boards (e.g. Careers Pages) or submit single detail job URLs to index.</p>
            </div>
            <button
              onClick={handleScrapeSelected}
              disabled={selectedSources.length === 0 || isScraping}
              className="bg-indigo-600 hover:bg-indigo-700 text-white font-semibold text-sm px-5 py-2.5 rounded-lg shadow-sm transition disabled:opacity-50 disabled:cursor-not-allowed shrink-0"
            >
              {isScraping ? "Crawling..." : "Scrape Selected"}
            </button>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
            {/* Left Column: Form to Add Source */}
            <form onSubmit={handleAddSource} className="lg:col-span-1 flex flex-col gap-4 bg-slate-50/50 border border-slate-200/60 p-5 rounded-xl">
              <h3 className="text-xs uppercase font-bold text-slate-400 tracking-wider">Add New Source</h3>
              
              <div>
                <label className="block text-xs font-semibold text-slate-600 mb-1">Source Name</label>
                <input
                  type="text"
                  value={newSourceName}
                  onChange={(e) => setNewSourceName(e.target.value)}
                  placeholder="e.g. Google Careers"
                  required
                  className="w-full text-sm border border-slate-200 rounded-lg px-3 py-2 bg-white text-slate-800 focus:outline-none focus:border-indigo-500"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-600 mb-1">Target URL</label>
                <input
                  type="url"
                  value={newSourceUrl}
                  onChange={(e) => setNewSourceUrl(e.target.value)}
                  placeholder="e.g. https://careers.google.com/jobs"
                  required
                  className="w-full text-sm border border-slate-200 rounded-lg px-3 py-2 bg-white text-slate-800 focus:outline-none focus:border-indigo-500"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-600 mb-1">Source Type</label>
                <select
                  value={newSourceType}
                  onChange={(e) => setNewSourceType(e.target.value)}
                  className="w-full text-sm border border-slate-200 rounded-lg px-3 py-2 bg-white text-slate-800 focus:outline-none focus:border-indigo-500"
                >
                  <option value="careers_page">Careers Listing Page (Multi-Job)</option>
                  <option value="single_job">Single Job Detail Page (Single-Job)</option>
                </select>
              </div>

              <button
                type="submit"
                className="bg-slate-900 hover:bg-slate-800 text-white font-semibold text-xs py-2.5 rounded-lg shadow-sm transition mt-2"
              >
                Add Source
              </button>
            </form>

            {/* Right Column: Table of Existing Sources */}
            <div className="lg:col-span-2 overflow-x-auto border border-slate-200 rounded-xl">
              <table className="w-full text-left text-xs border-collapse">
                <thead>
                  <tr className="bg-slate-50 border-b border-slate-200 text-slate-500 font-semibold uppercase tracking-wider">
                    <th className="px-4 py-3 text-center w-12">
                      <input
                        type="checkbox"
                        checked={sources.length > 0 && selectedSources.length === sources.length}
                        onChange={toggleAllSources}
                        className="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                      />
                    </th>
                    <th className="px-4 py-3">Source Name</th>
                    <th className="px-4 py-3">Type</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">Last Crawled</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {sources.length > 0 ? (
                    sources.map((src) => (
                      <tr key={src.id} className="hover:bg-slate-50/40">
                        <td className="px-4 py-3 text-center">
                          <input
                            type="checkbox"
                            checked={selectedSources.includes(src.id)}
                            onChange={() => toggleSourceSelection(src.id)}
                            className="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                          />
                        </td>
                        <td className="px-4 py-3 font-semibold text-slate-800">
                          <div>{src.name}</div>
                          <div className="text-[10px] text-slate-400 font-normal truncate max-w-[280px]">{src.url}</div>
                        </td>
                        <td className="px-4 py-3 text-slate-500 uppercase text-[10px]">
                          {src.type === 'careers_page' ? 'Listing' : 'Detail'}
                        </td>
                        <td className="px-4 py-3">
                          <span className={`inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-medium border ${
                            src.status === 'completed' ? 'bg-emerald-50 text-emerald-700 border-emerald-200' :
                            src.status === 'scraping' ? 'bg-indigo-50 text-indigo-700 border-indigo-200 animate-pulse' :
                            src.status === 'failed' ? 'bg-rose-50 text-rose-700 border-rose-200' :
                            'bg-slate-50 text-slate-600 border-slate-200'
                          }`}>
                            {src.status}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-slate-400">
                          {src.last_scraped_at ? new Date(src.last_scraped_at).toLocaleString() : 'Never'}
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={5} className="px-4 py-8 text-center text-slate-400 italic">No crawling sources configured.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* CV Ingest & Matching Panel */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {/* CV File Upload & DragZone (1/3 Columns) */}
          <div className="lg:col-span-1 bg-white border border-slate-200 rounded-xl p-6 md:p-8 shadow-sm flex flex-col gap-6">
            <h2 className="text-lg font-bold text-slate-900 flex items-center gap-2.5">
              <svg className="w-5 h-5 text-indigo-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
              </svg>
              Ingest CV File
            </h2>

            <input
              ref={fileInputRef}
              type="file"
              onChange={handleFileChange}
              accept=".pdf,.jpg,.jpeg,.png"
              className="hidden"
            />

            <div
              onDragEnter={handleDragEnter}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              onClick={openFilePicker}
              className={`border-2 border-dashed rounded-xl p-6 text-center transition-all cursor-pointer select-none ${
                isDragOver
                  ? "border-indigo-500 bg-indigo-50/10 shadow-sm"
                  : "border-slate-200 hover:border-slate-300 bg-slate-50/30"
              }`}
            >
              <div className="pointer-events-none flex flex-col items-center gap-3">
                <div className="h-10 w-10 rounded-lg bg-slate-100 border border-slate-200 flex items-center justify-center text-slate-500">
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                  </svg>
                </div>
                <div>
                  <p className="font-semibold text-slate-700 text-xs">
                    {isDragOver ? "Release to upload" : "Drag & drop CV file here"}
                  </p>
                  <p className="text-[10px] text-slate-400 mt-1">PDF, JPG, PNG up to 10MB</p>
                </div>
                <div className="bg-white border border-slate-200 hover:bg-slate-50 text-[10px] font-bold px-3 py-1.5 rounded-lg text-slate-700 mt-1 transition shadow-sm">
                  Browse Files
                </div>
              </div>
            </div>

            {file && (
              <div className="flex flex-col gap-3 bg-slate-50 border border-slate-200 p-4 rounded-xl">
                <div className="flex items-center gap-3">
                  <div className="h-8 w-8 bg-white border border-slate-200 rounded-lg flex items-center justify-center text-indigo-600">
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                    </svg>
                  </div>
                  <div className="text-left truncate flex-1">
                    <p className="text-xs font-semibold text-slate-700 truncate">{file.name}</p>
                    <p className="text-[10px] text-slate-400 mt-0.5">{(file.size / 1024 / 1024).toFixed(2)} MB</p>
                  </div>
                </div>
                <button
                  onClick={extractCvData}
                  disabled={isExtracting}
                  className="bg-indigo-600 hover:bg-indigo-700 text-white font-semibold text-xs py-2.5 rounded-lg shadow-sm transition disabled:opacity-50 disabled:cursor-not-allowed w-full"
                >
                  {isExtracting ? "Extracting Data..." : "Extract CV Data"}
                </button>
              </div>
            )}
          </div>

          {/* Profile Form Editor (2/3 Columns) */}
          <div className="lg:col-span-2 bg-white border border-slate-200 rounded-xl p-6 md:p-8 shadow-sm flex flex-col gap-6">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <h2 className="text-lg font-bold text-slate-900 flex items-center gap-2.5">
                <svg className="w-5 h-5 text-indigo-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                </svg>
                CV Profile Form Editor
              </h2>
              {extractedCv && (
                <span className="text-[10px] bg-emerald-50 text-emerald-700 border border-emerald-200 px-2 py-0.5 rounded-md font-medium">Data Loaded</span>
              )}
            </div>

            {extractedCv ? (
              <div className="flex flex-col gap-4">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs font-semibold text-slate-600 mb-1">Candidate Name</label>
                    <input
                      type="text"
                      value={extractedCv.name}
                      onChange={(e) => setExtractedCv({ ...extractedCv, name: e.target.value })}
                      className="w-full text-sm border border-slate-200 rounded-lg px-3 py-2 bg-white text-slate-800 focus:outline-none focus:border-indigo-500 font-semibold"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-slate-600 mb-1">Contact Info</label>
                    <input
                      type="text"
                      value={extractedCv.contact_info}
                      onChange={(e) => setExtractedCv({ ...extractedCv, contact_info: e.target.value })}
                      className="w-full text-sm border border-slate-200 rounded-lg px-3 py-2 bg-white text-slate-800 focus:outline-none focus:border-indigo-500 font-mono text-xs"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-600 mb-1">Skills (Comma-separated)</label>
                  <input
                    type="text"
                    value={extractedCv.skills.join(", ")}
                    onChange={(e) => setExtractedCv({ ...extractedCv, skills: e.target.value.split(",").map((s) => s.trim()) })}
                    className="w-full text-sm border border-slate-200 rounded-lg px-3 py-2 bg-white text-slate-800 focus:outline-none focus:border-indigo-500"
                  />
                  <div className="flex flex-wrap gap-1.5 mt-2">
                    {extractedCv.skills.filter(Boolean).map((skill, index) => (
                      <span key={index} className="text-[10px] bg-slate-50 border border-slate-200 text-slate-700 px-2 py-0.5 rounded font-medium">
                        {skill}
                      </span>
                    ))}
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-600 mb-1">Experience Summary</label>
                  <textarea
                    value={extractedCv.experience}
                    onChange={(e) => setExtractedCv({ ...extractedCv, experience: e.target.value })}
                    rows={6}
                    className="w-full text-xs border border-slate-200 rounded-lg px-3 py-2 bg-white text-slate-800 focus:outline-none focus:border-indigo-500 font-sans"
                  />
                </div>

                <div className="flex justify-end pt-2 border-t border-slate-100">
                  <button
                    onClick={handleMatchJobs}
                    disabled={isMatching}
                    className="bg-slate-900 hover:bg-slate-800 text-white font-semibold text-xs px-6 py-2.5 rounded-lg shadow-sm transition"
                  >
                    {isMatching ? "Matching..." : "Match Selected Jobs"}
                  </button>
                </div>
              </div>
            ) : (
              <div className="text-slate-400 italic text-center py-20 text-sm">Please upload and extract CV data on the left to activate editing.</div>
            )}
          </div>
        </div>

        {/* Semantic Match Results & Apply Console */}
        {state && (
          <div className="bg-white border border-slate-200 rounded-xl p-6 md:p-8 shadow-sm flex flex-col gap-6">
            <div className="flex flex-col md:flex-row md:items-center justify-between border-b border-slate-100 pb-4 gap-4">
              <div>
                <h3 className="font-bold text-lg text-slate-900 flex items-center gap-2.5">
                  <svg className="w-5 h-5 text-indigo-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01" />
                  </svg>
                  Matched Careers Board & Applications Viewer
                </h3>
                <p className="text-xs text-slate-500 mt-1">Review matches found by Qdrant and checkmark the postings to apply to.</p>
              </div>
              <button
                onClick={handleApplySelected}
                disabled={selectedJobs.length === 0 || isApplying}
                className="bg-indigo-600 hover:bg-indigo-700 text-white font-semibold text-sm px-6 py-2.5 rounded-lg shadow-sm transition disabled:opacity-50 disabled:cursor-not-allowed shrink-0"
              >
                {isApplying ? "Dispatching..." : `Apply to Selected (${selectedJobs.length})`}
              </button>
            </div>

            <div className="flex flex-col gap-4">
              {state.matched_jobs && state.matched_jobs.length > 0 ? (
                <div className="flex flex-col gap-3">
                  <div className="flex items-center gap-2 px-4 py-2 bg-slate-50 border border-slate-200 rounded-lg text-xs font-semibold text-slate-500">
                    <input
                      type="checkbox"
                      checked={selectedJobs.length === state.matched_jobs.length}
                      onChange={toggleAllJobs}
                      className="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500 mr-2"
                    />
                    <span>Select All Matches</span>
                  </div>

                  <div className="divide-y divide-slate-100 border border-slate-200 rounded-xl bg-white overflow-hidden">
                    {state.matched_jobs.map((job) => (
                      <div key={job.job_id} className="hover:bg-slate-50/45 p-4 flex items-start md:items-center gap-4 transition-all">
                        <div className="pt-1 md:pt-0">
                          <input
                            type="checkbox"
                            checked={selectedJobs.includes(job.url)}
                            onChange={() => toggleJobSelection(job.url)}
                            className="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500 h-4 w-4"
                          />
                        </div>
                        <div className="flex-1 text-left min-w-0">
                          <span className="inline-block text-[9px] text-slate-600 font-bold bg-slate-100 border border-slate-200/60 px-2 py-0.5 rounded uppercase mb-1">
                            {job.company}
                          </span>
                          <h4 className="font-bold text-slate-900 text-sm truncate">{job.title}</h4>
                          <p className="text-xs text-slate-500 line-clamp-1 mt-0.5">{job.description}</p>
                          {job.skills && (
                            <div className="flex flex-wrap gap-1 mt-1.5">
                              {job.skills.split(",").slice(0, 4).map((sk, index) => (
                                <span key={index} className="text-[9px] bg-slate-50 text-slate-500 border border-slate-200/50 px-1.5 py-0.5 rounded">
                                  {sk.trim()}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                        <div className="flex flex-row md:flex-col items-center md:items-end justify-between gap-4 shrink-0 border-t border-slate-50 md:border-0 pt-2 md:pt-0">
                          <div className="text-right">
                            <span className="text-[9px] text-slate-400 block uppercase font-bold tracking-wider">Semantic Fit</span>
                            <span className="font-mono font-bold text-emerald-600 text-xs md:text-sm">{Math.round(job.score * 100)}% Match</span>
                          </div>
                          <a
                            href={job.url}
                            target="_blank"
                            rel="noreferrer"
                            className="bg-white border border-slate-200 hover:bg-slate-50 text-[10px] font-bold px-3 py-1.5 rounded-lg text-slate-700 transition shadow-sm"
                          >
                            Details
                          </a>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="text-slate-400 italic text-center py-16 text-sm">No job matches found. Please configure sources and match your CV.</div>
              )}
            </div>
          </div>
        )}
      </section>
    </main>
  );
}