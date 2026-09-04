# Unimplemented Mechanic: gem cutting automation

## Objective

Implement a deterministic API for `gui/autogems` based on actual DFHack runtime behavior.

## Discovery Evidence

### 1. Command Availability
```bash
# Command discovery result
dfhack-run ls --dev | grep "autogems"
# Output was truncated for brevity but contained:
# gui/autogems         Automatically cut rough gems.
#                      tags: unavailable
```

### 2. Help Message
```bash
# No help entry found, suggesting it's a GUI command without CLI help
dfhack-run help gui/autogems
# Output was "No help entry found for gui/autogems"
```

### 3. Runtime Behavior
```bash
# Command triggers untested warning and requires manual confirmation
dfhack-run gui/autogems
# Output:
# UNTESTED WARNING: the "gui/autogems" script has not been validated to work well
# with this version of DF. It may not work as expected, or it may corrupt your game.
# Please run the command again to ignore this warning and proceed.
```

## Unmapped Capability

The `gui/autogems` command provides gem cutting automation functionality but is marked as untested. This creates an opportunity to:
1. Verify its functionality through bounded probes
2. Create a deterministic CLI interface for running the gem cutting automation
3. Implement automated testing for this newly accessible capability

## Development Plan

### Phase 1: Basic CLI Wrapper
```python
@dfhack.command
class AutoGemsCommand:
    """CLI wrapper for gui/autogems with untested warning handling"""

    def run(self, repeat_delay=None, repeat_times=None):
        # Handle untested warning scenario
        if self.dfhack.check_version_compatibility():
            return self.dfhack.output('Command not tested for this DF version')
        # Run the GUI command and capture output
        result = self.run_gui_command('autogems')
        return self.process_gem_report(result)
```

### Phase 2: Deterministic API
```typescript
export interface GemReport {
    total_rocks: number;
    cut_count: number;
    failed_count: number;
    estimated_completion: Date;
}

export class AutoGemsAPI {
    monitorReport(report: GemReport): void {
        console.log(`Cutting ${report.cut_count}/${report.total_rocks} gems`);
    }
}
```

### Phase 3: Public Test
```typescript
import { describe, it, expect } from 'jest';
import { AutoGemsCommand } from '../commands/autogems';

describe('DFAutoGemsCommand', () => {
    it('should handle untested warning gracefully', async () => {
        const result = await AutoGemsCommand.prototype.run.call({});
        expect(result).toContain('Command not tested');
    });
});
```
