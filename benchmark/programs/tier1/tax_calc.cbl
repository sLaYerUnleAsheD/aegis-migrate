      * PROGRESSIVE INCOME TAX (tier 1)
      * Record (13 bytes): ID X(5) | INCOME 9(6)V99
      * First 10000.00 at 10 pct, next 30000.00 at 20 pct, rest at 30.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TAXCALC.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT TAX-FILE ASSIGN TO "input.dat"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  TAX-FILE.
       01  TAX-REC.
           05 TR-ID          PIC X(5).
           05 TR-INCOME      PIC 9(6)V99.

       WORKING-STORAGE SECTION.
       01  WS-EOF-FLAG       PIC X        VALUE "N".
           88 INPUT-DONE                  VALUE "Y".
       01  WS-TAX            PIC 9(7)V99  VALUE 0.
       01  WS-NET            PIC 9(7)V99  VALUE 0.
       01  WS-TOTAL-TAX      PIC 9(9)V99  VALUE 0.
       01  WS-COUNT          PIC 9(3)     VALUE 0.
       01  WS-INC-ED         PIC ZZZ,ZZ9.99.
       01  WS-TAX-ED         PIC ZZZ,ZZ9.99.
       01  WS-NET-ED         PIC ZZZ,ZZ9.99.
       01  WS-TOTAL-ED       PIC ZZ,ZZZ,ZZ9.99.

       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT TAX-FILE
           PERFORM READ-PARA
           PERFORM PROCESS-PARA UNTIL INPUT-DONE
           CLOSE TAX-FILE
           MOVE WS-TOTAL-TAX TO WS-TOTAL-ED
           DISPLAY "TAXPAYERS: " WS-COUNT " TOTAL TAX: " WS-TOTAL-ED
           STOP RUN.

       READ-PARA.
           READ TAX-FILE
               AT END SET INPUT-DONE TO TRUE
           END-READ.

       PROCESS-PARA.
           IF TR-INCOME <= 10000.00
               COMPUTE WS-TAX ROUNDED = TR-INCOME * 0.10
           ELSE
               IF TR-INCOME <= 40000.00
                   COMPUTE WS-TAX ROUNDED =
                       1000.00 + (TR-INCOME - 10000.00) * 0.20
               ELSE
                   COMPUTE WS-TAX ROUNDED =
                       7000.00 + (TR-INCOME - 40000.00) * 0.30
               END-IF
           END-IF
           COMPUTE WS-NET = TR-INCOME - WS-TAX
           ADD WS-TAX TO WS-TOTAL-TAX
           ADD 1 TO WS-COUNT
           MOVE TR-INCOME TO WS-INC-ED
           MOVE WS-TAX TO WS-TAX-ED
           MOVE WS-NET TO WS-NET-ED
           DISPLAY TR-ID " " WS-INC-ED " " WS-TAX-ED " " WS-NET-ED
           PERFORM READ-PARA.