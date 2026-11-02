      * OVERFLOW DEMO (tier 3): accumulators too small ON PURPOSE.
      * Record (11 bytes): ACCT X(4) | AMT 9(5)V99
      * Only behaviour the COBOL standard defines is used:
      *  - WS-WRAP-TOTAL: MOVE from a larger field drops high digits
      *  - WS-SAFE-TOTAL: ON SIZE ERROR leaves the target unchanged
      *  - WS-HALF: no ROUNDED, so the result is truncated
      * The ON SIZE ERROR action is an out-of-line PERFORM. A nested
      * "ADD ... END-ADD" there is ambiguous and silently changes which
      * statements belong to the SIZE ERROR branch.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. OVFLDEMO.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT AMT-FILE ASSIGN TO "input.dat"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  AMT-FILE.
       01  AMT-REC.
           05 AR-ACCT        PIC X(4).
           05 AR-AMT         PIC 9(5)V99.

       WORKING-STORAGE SECTION.
       01  WS-EOF-FLAG       PIC X        VALUE "N".
           88 INPUT-DONE                  VALUE "Y".
       01  WS-BIG-TOTAL      PIC 9(7)V99  VALUE 0.
       01  WS-WRAP-TOTAL     PIC 9(5)V99  VALUE 0.
       01  WS-SAFE-TOTAL     PIC 9(5)V99  VALUE 0.
       01  WS-OVERFLOWS      PIC 99       VALUE 0.
       01  WS-COUNT          PIC 99       VALUE 0.
       01  WS-HALF           PIC 9(5)V9   VALUE 0.
       01  WS-AMT-ED         PIC ZZ,ZZ9.99.
       01  WS-WRAP-ED        PIC ZZ,ZZ9.99.
       01  WS-SAFE-ED        PIC ZZ,ZZ9.99.
       01  WS-HALF-ED        PIC ZZ,ZZ9.9.

       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT AMT-FILE
           PERFORM READ-PARA
           PERFORM PROCESS-PARA UNTIL INPUT-DONE
           CLOSE AMT-FILE
           PERFORM SUMMARY-PARA
           STOP RUN.

       READ-PARA.
           READ AMT-FILE
               AT END SET INPUT-DONE TO TRUE
           END-READ.

       PROCESS-PARA.
           ADD AR-AMT TO WS-BIG-TOTAL
           MOVE WS-BIG-TOTAL TO WS-WRAP-TOTAL
           ADD AR-AMT TO WS-SAFE-TOTAL
               ON SIZE ERROR
                   PERFORM OVERFLOW-PARA
           END-ADD
           ADD 1 TO WS-COUNT
           COMPUTE WS-HALF = AR-AMT / 2
           MOVE AR-AMT TO WS-AMT-ED
           MOVE WS-WRAP-TOTAL TO WS-WRAP-ED
           MOVE WS-SAFE-TOTAL TO WS-SAFE-ED
           MOVE WS-HALF TO WS-HALF-ED
           DISPLAY AR-ACCT " " WS-AMT-ED " " WS-WRAP-ED " "
               WS-SAFE-ED " " WS-HALF-ED
           PERFORM READ-PARA.

       SUMMARY-PARA.
           DISPLAY "RECORDS: " WS-COUNT
           DISPLAY "OVERFLOWS: " WS-OVERFLOWS.

       OVERFLOW-PARA.
           ADD 1 TO WS-OVERFLOWS.