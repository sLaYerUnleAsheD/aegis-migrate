import subprocess
import os

def get_cobol_output(source_path):
    """
    Compiles a COBOL source file and executes it.
    Returns the standard output as a string.
    """
    # Extract the directory and the base filename (e.g., 'hello' from 'hello.cbl')
    directory = os.path.dirname(source_path) or "."
    base_name = os.path.splitext(os.path.basename(source_path))[0]
    binary_path = os.path.join(directory, base_name)
    print(directory)
    print(base_name)
    print(binary_path)

    # Step 1: Compile the COBOL code
    compile_cmd = ['cobc', '-x', source_path, '-o', binary_path]
    compile_result = subprocess.run(compile_cmd, capture_output=True, text=True)

    if compile_result.returncode != 0:
        raise RuntimeError(f"Compilation failed:\n{compile_result.stderr}")

    # Step 2: Execute the compiled binary
    # Note: We pass the explicit path so Linux knows exactly where the binary is
    run_cmd = [f"./{binary_path}"]
    run_result = subprocess.run(run_cmd, capture_output=True, text=True)

    if run_result.returncode != 0:
        raise RuntimeError(f"Execution failed:\n{run_result.stderr}")

    # Step 3: Return the captured output
    return run_result.stdout

if __name__ == "__main__":
    # Test the function using your baseline program
    target_program = "../benchmark/programs/hello.cbl"
    
    print(f"Extracting golden output from {target_program}...\n")
    golden_output = get_cobol_output(target_program)
    
    print("=== CAPTURED OUTPUT ===")
    print(golden_output)
    print("=======================")