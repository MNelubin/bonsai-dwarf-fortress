-- Run the fort free with a COARSE heartbeat, and report what the manager machinery is
-- doing while it runs.
--
-- The fine-grained heartbeat this replaces cleared `status.popups` on every graphic
-- frame, which starved every fort of migrants and announcements — DF's fort-level
-- services ride on that same machinery. Clearing every `period` frames instead leaves
-- the event system alive while still unsticking a modal popup, which otherwise freezes
-- the sim outright (plain `pause_state = false` advanced one tick in four minutes).
--
--   bonsai-run <frames> [period]
--
-- Writes one progress line per period to /tmp/orderwatch.<port>.log so the run can be
-- followed without holding an RPC connection open for the whole chunk.

local frames = tonumber((...)) or 20000
local period = tonumber((select(2, ...))) or 500
local w = df.global.world
local pi = df.global.plotinfo
local start = w.frame_counter
local path = '/tmp/orderwatch.' .. (os.getenv('DFHACK_PORT') or 'x') .. '.log'

local function order_line()
    -- only the tail: a hand-played fort carries dozens of library orders whose state
    -- is not what is under test, and they drown the line we came to read
    local all = w.manager_orders.all
    local parts = {}
    for i = math.max(0, #all - 3), #all - 1 do
        local o = all[i]
        parts[#parts + 1] = string.format('#%d %s left=%d val=%s act=%s',
            o.id, df.job_type[o.job_type] or '?', o.amount_left,
            tostring(o.status.validated), tostring(o.status.active))
    end
    return #parts > 0 and table.concat(parts, ' | ') or 'no-orders'
end

local function job_count()
    local n = 0
    local ok = pcall(function()
        local link = w.jobs.list.next
        while link do n = n + 1; link = link.next end
    end)
    return ok and n or -1
end

-- Validation is not a timer tick: the manager takes a ManageWorkOrders job and does it
-- in their office. So the thing worth catching is that job appearing at all — on a fort
-- where orders never validate it never does, and everything else is downstream of that.
local seen_manage = false
local function manage_job()
    local found
    pcall(function()
        local link = w.jobs.list.next
        while link do
            local j = link.item
            if j and j.job_type == df.job_type.ManageWorkOrders then found = j; break end
            link = link.next
        end
    end)
    if not found then return '' end
    if not seen_manage then
        seen_manage = true
        local f = io.open(path, 'a')
        if f then
            f:write(string.format('MANAGE_JOB id=%d pos=%d,%d,%d holder=%s worker=%s flags=%s\n',
                found.id, found.pos.x, found.pos.y, found.pos.z,
                tostring(dfhack.job.getHolder(found) and dfhack.job.getHolder(found).id),
                tostring(dfhack.job.getWorker(found) and dfhack.job.getWorker(found).id),
                tostring(found.flags.by_manager)))
            f:close()
        end
    end
    return ' MANAGE'
end

local function log(tag)
    local f = io.open(path, 'a')
    if not f then return end
    f:write(string.format('%s f=%d tick=%d units=%d mgr_timer=%s jobs=%d %s%s\n',
        tag, w.frame_counter, df.global.cur_year_tick,
        #w.units.active, tostring(pi.manager_timer), job_count(), order_line(),
        manage_job()))
    f:close()
end

local function heartbeat()
    pcall(function() w.status.popups:resize(0) end)
    log('..')
    if w.frame_counter - start >= frames then
        df.global.pause_state = true
        log('END')
        return
    end
    df.global.pause_state = false
    dfhack.timeout(period, 'frames', heartbeat)
end

log('BEGIN')
heartbeat()
print(string.format('RUN start=%d frames=%d period=%d log=%s',
    start, frames, period, path))
